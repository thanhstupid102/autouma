import hashlib
import os
import platform
import shutil
import socket
import uuid
from pathlib import Path

from uma_api.errors import NodeDependenciesError


__all__ = [
    "get_gpu",
    "get_os",
    "get_ip",
    "get_hwid",
    "get_steam_machine_name",
    "check_deps",
]

DIR = str(Path(__file__).resolve().parent.parent)

_DEFAULT_DEVICE_NAME = "System Product Name (ASUSTeK COMPUTER INC.)"
_DEFAULT_GPU_NAME = "NVIDIA GeForce RTX 3060"
_DEFAULT_OS_VERSION = "Windows 11  (10.0.26100) 64bit"
_STEAM_MACHINE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _environment_override(name):
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _windows_plausible(value, fallback):
    if not value or "linux" in value.casefold():
        return fallback
    return value


def _read_system_value(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""


def _non_windows_machine_id():
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        value = _read_system_value(path)
        if value:
            return value
    return ""


def _non_windows_device_name():
    product = _read_system_value("/sys/class/dmi/id/product_name")
    vendor = _read_system_value("/sys/class/dmi/id/board_vendor")
    if product:
        value = f"{product} ({vendor})" if vendor else product
        return _windows_plausible(value, _DEFAULT_DEVICE_NAME)
    return _DEFAULT_DEVICE_NAME


def _machine_identity_material():
    if platform.system() == "Windows":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\BIOS",
            ) as bios_key:
                device_name, _ = winreg.QueryValueEx(
                    bios_key, "SystemProductName",
                )
                device_name = str(device_name).strip()
                try:
                    board_mfg, _ = winreg.QueryValueEx(
                        bios_key, "BaseBoardManufacturer",
                    )
                    if board_mfg:
                        device_name = (
                            f"{device_name} ({str(board_mfg).strip()})"
                        )
                except OSError:
                    pass
            if not device_name:
                raise RuntimeError(
                    "System product name returned empty. Refusing to start."
                )

            machine_guid = ""
            try:
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Cryptography",
                ) as crypto_key:
                    machine_guid, _ = winreg.QueryValueEx(
                        crypto_key, "MachineGuid",
                    )
            except OSError:
                pass
        except Exception as exc:
            raise RuntimeError(
                f"Failed to fetch system product name: {exc}. "
                "Refusing to start."
            ) from exc
    else:
        device_name = _non_windows_device_name()
        machine_guid = _non_windows_machine_id()

    device_name_override = _environment_override("UMA_DEVICE_NAME")
    if device_name_override is not None:
        device_name = _windows_plausible(
            device_name_override, _DEFAULT_DEVICE_NAME,
        )
    machine_guid = (
        _environment_override("UMA_DEVICE_MACHINE_ID") or machine_guid
    )
    return device_name, str(machine_guid or "")


def get_steam_machine_name():
    """Return a stable Windows-shaped Steam client name for this machine."""
    device_name, machine_guid = _machine_identity_material()
    material = f"{device_name}_{machine_guid}".encode("utf-8")
    digest = hashlib.sha1(material).digest()
    suffix = "".join(
        _STEAM_MACHINE_ALPHABET[value % len(_STEAM_MACHINE_ALPHABET)]
        for value in digest[:7]
    )
    return f"DESKTOP-{suffix}"


def get_gpu():
    """Return the GPU string, honoring ``UMA_DEVICE_GRAPHICS_DEVICE_NAME``."""
    override = _environment_override("UMA_DEVICE_GRAPHICS_DEVICE_NAME")
    if override is not None:
        return _windows_plausible(override, _DEFAULT_GPU_NAME)

    if platform.system() != "Windows":
        return _DEFAULT_GPU_NAME

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Video") as video_key:
            for i in range(winreg.QueryInfoKey(video_key)[0]):
                adapter_guid = winreg.EnumKey(video_key, i)
                adapter_path = rf"SYSTEM\CurrentControlSet\Control\Video\{adapter_guid}\0000"
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, adapter_path) as adapter_key:
                        value, _ = winreg.QueryValueEx(adapter_key, "HardwareInformation.AdapterString")
                        if isinstance(value, bytes):
                            value = value.decode("utf-16-le", errors="ignore")
                        gpu_name = str(value).replace("\x00", "").strip()
                        if gpu_name:
                            return gpu_name
                except OSError:
                    continue
    except Exception as e:
        raise RuntimeError(f"Failed to fetch GPU info: {e}") from e

    raise RuntimeError("Failed to fetch GPU info: display adapter registry value empty")

def get_os():
    """Return the Windows-shaped OS string, honoring ``UMA_DEVICE_PLATFORM_OS_VERSION``."""
    override = _environment_override("UMA_DEVICE_PLATFORM_OS_VERSION")
    if override is not None:
        return _windows_plausible(override, _DEFAULT_OS_VERSION)
    if platform.system() == "Windows":
        return f"Windows 11  ({platform.version()}) 64bit"
    return _DEFAULT_OS_VERSION

def get_ip():
    """Best-effort local IPv4 address, honoring ``UMA_DEVICE_IP_ADDRESS``.

    A saved account's stored ``ip_address`` takes precedence over this probe, so
    these fallbacks affect only brand-new or incomplete device identities.
    """
    override = _environment_override("UMA_DEVICE_IP_ADDRESS")
    if override is not None:
        return override

    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname()) or "127.0.0.1"
        except Exception:
            return "127.0.0.1"
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass

def get_hwid(seed_string="default"):
    """Return a stable Windows-shaped device profile on every supported host.

    Operators can override synthesized or probed values on both Windows and
    non-Windows hosts with ``UMA_DEVICE_NAME``,
    ``UMA_DEVICE_GRAPHICS_DEVICE_NAME``, ``UMA_DEVICE_PLATFORM_OS_VERSION``,
    ``UMA_DEVICE_IP_ADDRESS``, and ``UMA_DEVICE_MACHINE_ID``. The machine-id
    override participates in ``device_id`` generation and is not sent directly.
    Overrides used for wire-visible names should remain Windows-PC-plausible.
    """
    guid = str(uuid.uuid4()).lower()

    device_name, machine_guid = _machine_identity_material()

    hardware_string = f"{device_name}_{machine_guid}_{seed_string}"
    device_id = hashlib.sha1(hardware_string.encode()).hexdigest()

    return {
        'device_name': device_name,
        'graphics_device_name': get_gpu(),
        'platform_os_version': get_os(),
        'ip_address': get_ip(),
        'udid': guid,
        'device_id': device_id
    }

def check_deps():
    """Verify the Node prerequisites required by the Steam auth scripts."""
    install_help = f'Run "npm install" in {DIR} to install the Node dependencies.'
    if not shutil.which("node"):
        raise NodeDependenciesError(
            "Node.js is not available on PATH. Install Node.js ^20.19.0 or "
            f">=22.12.0. {install_help}"
        )

    node_modules = Path(DIR) / "node_modules"
    missing = [
        package
        for package in ("steam-user", "steam-session")
        if not (node_modules / package / "package.json").is_file()
    ]
    if missing:
        raise NodeDependenciesError(
            f"Missing Node dependencies: {', '.join(missing)}. {install_help}"
        )

