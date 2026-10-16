"""Type-only contract of the ``UmaClient`` state the ``ApiRoutes`` mixin borrows.

``ApiRoutes`` (uma_api/routes.py) is mixed into ``UmaClient`` (uma_api/client.py)
and is only ever used that way -- every route helper reaches for ``self.call``,
the cached ``tp_info``, the ``hard_reset`` recovery entry point and the active
``current_scenario_id``, none of which the mixin itself defines. From the mixin's
point of view those names simply come "from the host", which a type checker
cannot infer. This module declares that host contract once so mypy can check the
mixin's bodies (§12.6 typing floor).

It is TYPE-ONLY and has no runtime effect whatsoever:

* the class body is bare annotations plus a ``TYPE_CHECKING``-guarded block, so
  it defines no runtime attribute or method;
* ``ApiRoutes`` inherits it only under ``TYPE_CHECKING`` (see the ``_HostState``
  alias at the top of routes.py), so at runtime ``ApiRoutes.__mro__`` is exactly
  ``(ApiRoutes, object)``, ``UmaClient.__mro__`` is unchanged, and this module is
  never even imported.

Adding state to ``UmaClient`` that a route helper reads? Declare it here too,
otherwise the mixin will not type-check.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any


class UmaClientState:
    # Set to None in UmaClient.__init__ and to an int by routes.py /
    # client.py once the active career's scenario is known.
    current_scenario_id: int | None
    # Raw server tp_info row, cached by refresh_cached_account_state.
    tp_info: dict[str, Any]
    # Writable state root selected by the process-wide resolver.
    state_root: Path

    if TYPE_CHECKING:
        # --- helpers implemented on UmaClient (uma_api/client.py) ------------
        # The bodies below are unreachable at runtime (TYPE_CHECKING is False);
        # the real implementations live in client.py.

        # The single wire entry point. Deliberately `Any`: the decoded server
        # envelope is raw JSON reshaped per endpoint, and every caller treats it
        # structurally.
        def call(
            self,
            ep: str,
            args: dict[str, Any] | None = None,
            retry_208: int = 6,
            retry_205: int = 3,
            retry_500: int = 3,
            _ver_retry: bool = False,
        ) -> Any:
            raise NotImplementedError

        def hard_reset(self) -> Any:
            raise NotImplementedError
