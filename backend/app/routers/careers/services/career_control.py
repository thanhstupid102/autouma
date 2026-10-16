from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only base: declares the CareerService state / sibling-mixin handlers
    # this mixin borrows. At runtime the base is plain `object`, so the MRO is
    # exactly what `class CareerControlMixin:` would produce.
    from .service_state import CareerServiceState
    _HostState = CareerServiceState
else:
    _HostState = object


class CareerControlMixin(_HostState):
    def runner_status(self):
        session = self.session
        snap = session.runner.snapshot()
        snap["loop_active"] = session.loop_active()
        return {"success": True, "runner": snap}

    def stop_runner(self):
        session = self.session
        session.loop_stop = True
        session.runner.stop()
        return {"success": True, "runner": session.runner.snapshot()}

    def pause_runner(self):
        session = self.session
        # Pause = SAVE-AND-EXIT (user request): the runner exits the current career at its
        # next safe boundary (the career stays active server-side, resumable). loop_paused
        # halts the multi-run loop WITHOUT a hard stop -- using loop_stop here would make the
        # loop call runner.stop() and clobber the "paused" status.
        session.loop_paused = True
        session.runner.pause()
        return {"success": True, "runner": session.runner.snapshot()}

    def set_burn_clocks(self, burn_clocks: bool):
        session = self.session
        session.runner.set_burn_clocks(burn_clocks)
        return {"success": True, "runner": session.runner.snapshot()}

    def resume(self):
        session = self.session
        # If the runner is still alive (nothing exited yet), just clear the pause flag.
        if session.runner.snapshot().get("running") or session.loop_active():
            session.loop_paused = False
            session.runner.resume()
            return {"success": True, "runner": session.runner.snapshot()}
        # The runner exited via save-and-exit; the career is still active server-side. Re-run
        # it from the saved state using the stored run request (single or loop).
        if session.last_run_req is not None and session.client is not None:
            session.loop_paused = False
            session.runner.resume()  # clear the "paused" status before relaunch
            try:
                return self._launch_career_run(session.last_run_req, session.last_preset or {})
            except Exception as e:
                return {"success": False, "detail": str(e)}
        # Nothing to resume -- fall back to the no-op status clear.
        session.runner.resume()
        return {"success": True, "runner": session.runner.snapshot()}
