"""Console logging for the operator run log (§12.6 Logging, step L1).

The operator reads the process console as the live run log, so the root
handler renders message-only to stdout — byte-compatible with the print()
output it replaces. Configure ONCE at the CLI boundary (backend/app/cli.py);
library code only ever calls logging.getLogger(__name__) and never touches
handlers, so embedding the packages elsewhere (tests, tools) stays silent
unless the host configures logging itself.
"""

import logging
import sys

from uma_api.log_context import install_log_fields


def configure_console_logging(level: int = logging.INFO) -> None:
    """Idempotent root config: message-only stdout, like the prints it replaced.

    StreamHandler flushes on every emit, preserving the flush=True behavior of
    the print() calls this migration replaced. uvicorn.run(log_level=...) only
    configures the uvicorn.* loggers, so this root handler is untouched by it.

    Also installs the L2 structured-field record factory (uma_api.log_context).
    That is deliberately BEFORE the `root.handlers` early return: a host that
    already configured its own handlers still gets the machine-readable fields,
    and the "%(message)s" format below never renders them, so the operator's
    console stays byte-identical either way.
    """
    install_log_fields()
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    root.setLevel(level)
