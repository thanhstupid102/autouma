from datetime import datetime, timezone


def utc_iso_seconds() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def utc_filename_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def utc_clock() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def utc_log_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
