# Connect to environment variables
import logging
import os
from pathlib import Path

from .runtime_paths import resolve_master_mdb_path


DEFAULT_CAREER_API_BODY_MAX_BYTES = 2048
DEFAULT_CAREER_API_TRACE_ENABLED = True
DEFAULT_CAREER_API_TRACE_MAX_BYTES = 256 * 1024 * 1024
DEFAULT_CAREER_API_TRACE_MIN_FREE_BYTES = 512 * 1024 * 1024
DEFAULT_DISCORD_CAREER_TRACE_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_CAREER_CIRCUIT_RETRY_WAIT_SECONDS = (5, 15, 30)

log = logging.getLogger("settings")


def career_api_body_max_bytes():
    """Read the optional career-report body cap without blocking startup."""
    raw = os.environ.get("UMA_MAX_CAREER_API_BODY_BYTES")
    if not raw:
        return DEFAULT_CAREER_API_BODY_MAX_BYTES
    try:
        return max(0, int(raw))
    except ValueError:
        log.warning(
            "Invalid UMA_MAX_CAREER_API_BODY_BYTES value %r; "
            "using default %d bytes",
            raw,
            DEFAULT_CAREER_API_BODY_MAX_BYTES,
        )
        return DEFAULT_CAREER_API_BODY_MAX_BYTES


def career_circuit_retry_wait_seconds():
    """Read the three escalating circuit-breaker cooldowns."""
    raw = os.environ.get("UMA_CAREER_CIRCUIT_RETRY_WAIT_SECONDS")
    if not raw:
        return DEFAULT_CAREER_CIRCUIT_RETRY_WAIT_SECONDS
    try:
        values = tuple(int(part.strip()) for part in raw.split(","))
        if (
            len(values) != len(DEFAULT_CAREER_CIRCUIT_RETRY_WAIT_SECONDS)
            or any(value <= 0 for value in values)
        ):
            raise ValueError
        return values
    except ValueError:
        log.warning(
            "Invalid UMA_CAREER_CIRCUIT_RETRY_WAIT_SECONDS value %r; "
            "using default %s seconds",
            raw,
            ",".join(
                str(value)
                for value in DEFAULT_CAREER_CIRCUIT_RETRY_WAIT_SECONDS
            ),
        )
        return DEFAULT_CAREER_CIRCUIT_RETRY_WAIT_SECONDS


def career_api_trace_enabled():
    """Enable the run-scoped full API sidecar without blocking startup."""
    raw = os.environ.get("UMA_CAREER_API_TRACE")
    if raw is None or not raw.strip():
        return DEFAULT_CAREER_API_TRACE_ENABLED
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    log.warning(
        "Invalid UMA_CAREER_API_TRACE value %r; using default %s",
        raw,
        int(DEFAULT_CAREER_API_TRACE_ENABLED),
    )
    return DEFAULT_CAREER_API_TRACE_ENABLED


def discord_career_trace_max_bytes():
    """Read the Discord attachment ceiling without blocking startup."""
    raw = os.environ.get("UMA_DISCORD_CAREER_TRACE_MAX_BYTES")
    if not raw:
        return DEFAULT_DISCORD_CAREER_TRACE_MAX_BYTES
    try:
        value = int(raw)
        if value <= 0:
            raise ValueError
        return value
    except ValueError:
        log.warning(
            "Invalid UMA_DISCORD_CAREER_TRACE_MAX_BYTES value %r; "
            "using default %d bytes",
            raw,
            DEFAULT_DISCORD_CAREER_TRACE_MAX_BYTES,
        )
        return DEFAULT_DISCORD_CAREER_TRACE_MAX_BYTES


def _nonnegative_byte_setting(name, default):
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        log.warning(
            "Invalid %s value %r; using default %d bytes",
            name,
            raw,
            default,
        )
        return default


class Settings:
    # Path
    BASE_DIR = Path(__file__).parent.parent.absolute()
    PATH = {
        "data_json": BASE_DIR / 'data' / 'json',
        "frontend": BASE_DIR / 'frontend',
        "hooks": BASE_DIR / "integrations" / "frida" / "js",
        "settings": BASE_DIR / 'settings.json',
        "steam": BASE_DIR / "integrations" / "steam",
    }

    # Frida hook scripts (read as text and injected)
    JS_IL2CPP_THREAD_GUARD_HOOKS = PATH["hooks"] / "il2cpp_thread_guard.js"
    JS_NATIVE_HTTP_URLS_HOOKS = PATH["hooks"] / "native_http_urls.js"
    JS_UMA_FULL_TRAFFIC_HOOKS = PATH["hooks"] / "uma_full_traffic.js"
    JS_UMA_NETWORK_HOOKS = PATH["hooks"] / "uma_network.js"
    JS_UMA_RESOURCE_URLS_HOOKS = PATH["hooks"] / "uma_resource_urls.js"

    # Steam Node.js scripts (executed via `node <script>`)
    JS_STEAM_TICKET_GEN = PATH["steam"] / "steam_ticket_gen.js"
    JS_STEAM_QR_LOGIN = PATH["steam"] / "qr_login.js"

    DOC_URL = "/apis/docs"
    REDOC_URL = "/apis/redocs"

    # App settings
    APP_ID = "3224770"
    APP_PROCESS_NAME = "UmamusumePrettyDerby.exe"

    # Sweepy settings
    SWEEP_ACCOUNT = os.environ.get("SWEEP_ACCOUNT", None)
    SWEEPY_HOST = os.environ.get("SWEEPY_HOST", None)
    SWEEPY_PORT = os.environ.get("SWEEPY_PORT", None)
    SWEEPY_CIRCUIT_THRESHOLD = int(os.environ.get("SWEEPY_CIRCUIT_THRESHOLD", 6))
    SWEEPY_CIRCUIT_WINDOW_SEC = float(os.environ.get("SWEEPY_CIRCUIT_WINDOW_SEC", 90.0))
    # UMA settings
    UMA_TRACE = os.environ.get("UMA_TRACE")
    UMA_RUNTIME_DIR = os.environ.get("UMA_RUNTIME_DIR", None)
    UMA_MAX_CAREER_LOGS = max(1, int(os.environ.get("UMA_MAX_CAREER_LOGS") or 20))
    # Oversize API bodies become metadata markers; zero disables body capping.
    UMA_MAX_CAREER_API_BODY_BYTES = career_api_body_max_bytes()
    # Full request/response sidecar for post-mortem career debugging.
    UMA_CAREER_API_TRACE = career_api_trace_enabled()
    UMA_CAREER_API_TRACE_MAX_BYTES = _nonnegative_byte_setting(
        "UMA_CAREER_API_TRACE_MAX_BYTES",
        DEFAULT_CAREER_API_TRACE_MAX_BYTES,
    )
    UMA_CAREER_API_TRACE_MIN_FREE_BYTES = _nonnegative_byte_setting(
        "UMA_CAREER_API_TRACE_MIN_FREE_BYTES",
        DEFAULT_CAREER_API_TRACE_MIN_FREE_BYTES,
    )
    UMA_DISCORD_CAREER_TRACE_MAX_BYTES = discord_career_trace_max_bytes()
    UMA_CAREER_CIRCUIT_RETRY_WAIT_SECONDS = career_circuit_retry_wait_seconds()
    UMA_MAX_TRACE_LOGS = max(1, int(os.environ.get("UMA_MAX_TRACE_LOGS") or 20))

    # Other settings
    LOCAL_APP_DATA = os.environ.get("LOCALAPPDATA", None)
    MASTER_MDB_PATH = resolve_master_mdb_path(BASE_DIR)

    # Support Card Data
    CARD_RARITY = {
        1: "R",
        2: "SR",
        3: "SSR",
    }
    CARD_TYPE = {
        2: "Friends",
        3: "Group",
    }
    STATS_TYPE = {
        101: "Speed",
        102: "Power",
        103: "Guts",
        105: "Stamina",
        106: "Wisdom",
    }

    # Game Data
    MONTH_LABELS = [
        "",
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]

    YEAR_LABELS = {
        0: "Junior Year",
        24: "Classic Year",
        48: "Senior Year",
    }

    GRADE_LABELS = {
        100: "G1",
        200: "G2",
        300: "G3",
        400: "OP",
        700: "PRE-OP",
    }

    TRACK_LABELS = {
        10001: "Sapporo",
        10002: "Hakodate",
        10003: "Niigata",
        10004: "Fukushima",
        10005: "Nakayama",
        10006: "Tokyo",
        10007: "Chukyo",
        10008: "Kyoto",
        10009: "Hanshin",
        10010: "Kokura",
        10101: "Ooi",
    }
