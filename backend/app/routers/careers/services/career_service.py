from uma_api.session import Session

from .career_start import CareerStartMixin
from .career_run import CareerRunMixin
from .career_control import CareerControlMixin
from .career_query import CareerQueryMixin


class CareerService(CareerStartMixin, CareerRunMixin, CareerControlMixin, CareerQueryMixin):
    """Full-move (verbatim) handlers for the career start/run/runner-control routes
    plus the event-info/resume/friends/action/delete-career routes. Boundary helpers
    are imported normally at module level from ``backend.app.domain``, which sits
    BELOW ``routers`` in the import graph: there is no cycle to dodge, so none of
    these imports need to be deferred to call time."""

    def __init__(self, session: Session):
        self.session = session
