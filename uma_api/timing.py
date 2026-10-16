"""Two SEPARATE timing seams for the transport client (REFACTOR_PLAN.md §13.2, B3).

`uma_api.client` used to `from career_bot.delay import ...` at module scope -- an
upward import from transport into the application layer -- and then used those five
primitives for **two different things** that must never be merged into one policy:

  (a) **transport retry / backoff waits** -- how long to wait before re-sending a
      request the server or the socket just refused (network exception, HTTP 5xx,
      result_code 500 / 205, the non-batch 208 ladder, and the 394/202 login
      retries). `backoff_sleep` and `server_sleep` are deliberately NOT gated on the
      No-CD toggle: they are server-mandated waits, not human pacing.

  (b) **per-account human pacing** -- the anti-detection rhythm of a real player.
      The 0.14s inter-call floor, the api_jitter draw, and the signup step pause all
      run through the account's `TimingDNA` and are silenced by that account's No-CD
      toggle. Changing any of them changes LIVE REQUEST PACING on a real account.

Collapsing the two into one "timing policy" would make a retry-tuning change silently
re-time the anti-detection profile (or vice versa), so there are two classes here and
they are injected independently.

The default implementations are pure forwarders: they resolve the primitive **by name,
at call time, from the module the client hands them** (`uma_api.client`), which keeps
the long-standing `monkeypatch.setattr(client_mod, "backoff_sleep", ...)` seam that
8 test modules rely on working exactly as before. The module-level shims below are what
those names now point at: `career_bot.delay` is imported *inside* the call, so importing
`uma_api.client` no longer drags the decision engine into the process.
"""
from typing import Any


def _delay() -> Any:
    """`career_bot.delay`, imported at CALL time.

    Transport must not import the application layer at module scope; every value
    here was already read per-call from that module, so semantics are unchanged.
    """
    from career_bot import delay

    return delay


# --- module-level primitives (the names uma_api.client re-exports as its hooks) ---

def dna_sleep(min_val: float, max_val: float,
              mean: float | None = None, stddev: float | None = None) -> float:
    return _delay().dna_sleep(min_val, max_val, mean, stddev)


def dna_uniform(min_val: float, max_val: float) -> float:
    return _delay().dna_uniform(min_val, max_val)


def dna_gauss(mean: float, stddev: float) -> float:
    return _delay().dna_gauss(mean, stddev)


def jittered_sleep(seconds: float, spread: float = 0.3) -> float:
    return _delay().jittered_sleep(seconds, spread)


def backoff_sleep(attempt: int, base: float = 1.0, cap: float = 15.0,
                  factor: float = 2.0) -> float:
    return _delay().backoff_sleep(attempt, base=base, cap=cap, factor=factor)


def server_sleep(min_val: float, max_val: float) -> float:
    return _delay().server_sleep(min_val, max_val)


# --- seam (a): transport retry / backoff waits -------------------------------

class TransportRetryPolicy:
    """How long the transport waits before re-sending a refused request.

    Every method mirrors the primitive it replaced 1:1 -- same name, same argument
    order, same defaults -- so a wait can be re-timed here without touching pacing.
    """

    def __init__(self, source: Any) -> None:
        # Resolved by NAME at call time (never captured), so the module-level hook
        # remains the monkeypatch seam it has always been.
        self._source = source

    def backoff_sleep(self, attempt: int, base: float = 1.0, cap: float = 15.0) -> float:
        """Exponential backoff with equal jitter. Ignores No-CD by design."""
        return self._source.backoff_sleep(attempt, base=base, cap=cap)

    def server_sleep(self, min_val: float, max_val: float) -> float:
        """A server-mandated wait (result_code 205). Ignores No-CD by design."""
        return self._source.server_sleep(min_val, max_val)

    def jittered_sleep(self, seconds: float) -> float:
        """Login-retry wait after 394 / 202. No-CD gated, as it always was."""
        return self._source.jittered_sleep(seconds)


# --- seam (b): per-account human pacing --------------------------------------

class AccountPacingPolicy:
    """The account's anti-detection rhythm -- everything the No-CD toggle silences.

    ⚠️ Every number reachable through here is LIVE REQUEST PACING on a real account.
    """

    def __init__(self, source: Any) -> None:
        self._source = source

    def dna_sleep(self, min_val: float, max_val: float) -> float:
        """The 0.14s minimum gap between raw calls (per-account, No-CD gated)."""
        return self._source.dna_sleep(min_val, max_val)

    def dna_uniform(self, min_val: float, max_val: float) -> float:
        """A draw from this account's TimingDNA (api_jitter). Not a sleep."""
        return self._source.dna_uniform(min_val, max_val)

    def jittered_sleep(self, seconds: float) -> float:
        """The signup pre_signup -> signup step pause (No-CD gated)."""
        return self._source.jittered_sleep(seconds)
