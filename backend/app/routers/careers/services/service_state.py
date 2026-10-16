"""Type-only contract of the state and helpers CareerService's mixins share.

``CareerService`` (career_service.py) is assembled from four mixins -- start /
run / control / query -- and every one of them reaches for the ``session`` that
``CareerService.__init__`` binds, while two of them also call a handler
implemented in a *sibling* mixin (``resume`` -> ``_launch_career_run``,
``_launch_career_run`` -> ``start_career_from_request``). From any single
mixin's point of view those names simply come "from the host", which a type
checker cannot infer. This module declares that host contract once so mypy can
check the mixin bodies (§12.6 typing floor); it replaces the three ad-hoc
``if TYPE_CHECKING: session: Session`` blocks the mixins used to carry
individually (``CareerQueryMixin`` carried none, which is what surfaced).

It is TYPE-ONLY and has no runtime effect whatsoever:

* the class body is bare annotations plus a ``TYPE_CHECKING``-guarded block, so
  it defines no runtime attribute or method;
* the mixins inherit it only under ``TYPE_CHECKING`` (see the ``_HostState``
  alias at the top of each mixin module), so at runtime each mixin's MRO is
  exactly ``(Mixin, object)``, ``CareerService.__mro__`` is unchanged, and this
  module is never even imported.

Adding state to ``CareerService`` -- or calling a sibling mixin's handler --?
Declare it here too, otherwise the mixin that uses it will not type-check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uma_api.session import Session


class CareerServiceState:
    # Bound by CareerService.__init__ (career_service.py); every mixin's first
    # statement is some form of `session = self.session`.
    session: Session

    if TYPE_CHECKING:
        # --- handlers a mixin borrows from a sibling mixin -------------------
        # The bodies below are unreachable at runtime (TYPE_CHECKING is False);
        # the real implementations live in the module named above each group.
        # `req` / `preset` stay Any: they are the raw request model and the
        # mutable preset dict, both reshaped ad hoc across these handlers.

        # career_start.py
        def start_career_from_request(self, req: Any) -> dict[str, Any]:
            raise NotImplementedError

        # career_run.py
        def _launch_career_run(self, req: Any, preset: Any) -> dict[str, Any]:
            raise NotImplementedError
