"""Structured log fields (§12.6 Logging, step **L2**) -- console output unchanged.

L1 turned 168 ``print()`` calls into ``logging`` calls with the message text frozen
byte-for-byte, because **the operator reads the process console AS the live run
log**. L2 adds machine-readable context (``account`` / ``endpoint`` / ``turn`` /
``scenario_id`` / ``result_code``) *next to* that text, for a future file/JSON sink
-- it must never change one character of what the operator sees.

How it works
------------
A ``LogRecord`` **factory** (``logging.setLogRecordFactory``) stamps the five
fields onto every record at creation time, reading them from a single
``contextvars.ContextVar`` that holds an immutable mapping. Producers open a
scope (``log_context``) or update the ambient values (``set_log_fields``); the
call sites themselves are untouched -- ``log.warning(f"...")`` stays exactly as
L1 left it.

Why a record factory and not a filter or ``LoggerAdapter``
----------------------------------------------------------
* A ``Filter`` on the **root logger** never sees records from child loggers:
  ``Logger.filter()`` runs only in the ``Logger.handle()`` of the logger the call
  originated on; propagation to ancestors goes through ``callHandlers``, which
  walks ancestor *handlers*, not ancestor *filters*. A filter on the **root
  handler** would work for the console but not for any other sink -- notably
  pytest's ``caplog`` handler, which is a different handler entirely.
* A ``LoggerAdapter`` would have to be threaded through every module and mixin
  (``log`` -> ``self._log_adapter``), i.e. exactly the per-call-site boilerplate
  this step is meant to avoid, and it cannot carry a value (``turn``) that
  changes underneath a long-lived module-level logger.
* The factory runs for *every* record from *every* logger, so the schema is
  uniform and a future JSON sink can rely on all five keys always existing.

Console safety
--------------
``backend.app.logging_setup.configure_console_logging`` formats with ``%(message)s``.
Extra record attributes are simply never referenced by that format string, so the
rendered bytes are identical with and without this module installed (pinned by
``tests/test_log_context.py``).

Threading
---------
The run loop is threaded: one ``CareerRunner`` thread per account plus a live
monitor thread. ``contextvars`` is the right primitive here because **a newly
started ``threading.Thread`` begins with an EMPTY context** -- it does not
inherit the creating thread's values (unlike ``asyncio.Task``, which copies).
So:

* binding on the caller's thread (e.g. inside ``CareerRunner.start``) would NOT
  reach the runner thread, and would leave the web/CLI thread permanently
  polluted -- the bind therefore happens at the *thread entry point*;
* two runner threads can never observe each other's account;
* the monitor thread sees no fields at all, which is correct (it is not running
  any one account's career).

``log_context`` additionally scopes the values with a ``Token`` and resets them in
a ``finally``, so nesting composes and a *reused* thread (a pool worker, which
does keep its context between tasks) cannot leak into its next occupant.

Interaction with ``extra=``
---------------------------
Do **not** pass these five names through ``logging``'s ``extra=`` argument.
``Logger.makeRecord`` raises ``KeyError`` for any ``extra`` key already present in
the record's ``__dict__``, and the factory has already put all five there. Use
``with log_context(result_code=...)`` (or ``set_log_fields``) for a one-off
override instead; pinned by ``test_extra_kwarg_for_a_managed_field_is_rejected``.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
from typing import Any, Callable, Dict, Iterator, Mapping, Optional

#: The record attributes this module owns. Every LogRecord gets all of them
#: (``None`` when unbound) so the schema a machine sink reads is uniform.
#: None of these collide with a stdlib ``LogRecord`` attribute -- pinned by
#: ``test_managed_fields_do_not_collide_with_logrecord_attributes``.
LOG_FIELDS = ("account", "endpoint", "turn", "scenario_id", "result_code")

_EMPTY: Mapping[str, Any] = {}

# ONE var holding an immutable mapping, not five vars: a scope is a single
# set/reset, the factory does a single lookup, and adding a field later is a dict
# key rather than a new module global. The mapping is never mutated in place --
# every update rebinds a fresh dict -- so a reader can never observe a torn value.
_log_fields: contextvars.ContextVar[Mapping[str, Any]] = contextvars.ContextVar(
    "uma_log_fields", default=_EMPTY,
)


class _FieldStampingFactory:
    """LogRecord factory that copies the ambient context fields onto the record.

    Wraps whatever factory was installed before it (usually ``logging.LogRecord``,
    but possibly another library's), so installing this is additive. Being a class
    rather than a closure makes the install idempotent via ``isinstance`` and makes
    the previous factory recoverable for ``uninstall_log_fields``.
    """

    def __init__(self, inner: Callable[..., logging.LogRecord]) -> None:
        self.inner = inner

    def __call__(self, *args: Any, **kwargs: Any) -> logging.LogRecord:
        record = self.inner(*args, **kwargs)
        fields = _log_fields.get()
        for name in LOG_FIELDS:
            setattr(record, name, fields.get(name))
        return record


def install_log_fields() -> None:
    """Install the field-stamping record factory. Idempotent, process-wide.

    Called by ``configure_console_logging`` at the CLI boundary (so production has
    it before the first log line) and lazily by ``log_context``/``set_log_fields``
    (so embedders and tests that never configure a console still get the fields).
    """
    factory = logging.getLogRecordFactory()
    if isinstance(factory, _FieldStampingFactory):
        return
    logging.setLogRecordFactory(_FieldStampingFactory(factory))


def uninstall_log_fields() -> None:
    """Restore the factory that was in place before ``install_log_fields``.

    Only used by tests (and by a host that wants the stdlib record back); the
    production process installs once and never removes.
    """
    factory = logging.getLogRecordFactory()
    if isinstance(factory, _FieldStampingFactory):
        logging.setLogRecordFactory(factory.inner)


def current_log_fields() -> Dict[str, Any]:
    """Snapshot of the fields bound on THIS thread (a copy; safe to mutate)."""
    return dict(_log_fields.get())


def set_log_fields(**fields: Optional[Any]) -> None:
    """Merge ``fields`` into this thread's ambient context, with no scope.

    For values that move forward monotonically inside an already-scoped region --
    the career's current ``turn``, the endpoint of the last API call. Pass ``None``
    to clear a field. Because an enclosing ``log_context`` resets by ``Token``, any
    number of these are undone when that scope exits.
    """
    install_log_fields()
    _log_fields.set({**_log_fields.get(), **fields})


@contextlib.contextmanager
def log_context(**fields: Optional[Any]) -> Iterator[None]:
    """Bind ``fields`` for the duration of the block, on this thread only.

    Restores the previous mapping on exit -- including on an exception, and
    including any ``set_log_fields`` performed inside -- so scopes nest and a
    reused thread cannot leak.
    """
    install_log_fields()
    token = _log_fields.set({**_log_fields.get(), **fields})
    try:
        yield
    finally:
        _log_fields.reset(token)
