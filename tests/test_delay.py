import career_bot.delay as d
from backend.app.routers.settings.services.delay import DelayConfigService
from tests._helpers import _make_session


# ---------------------------------------------------------------------------
# Per-account pacing lives on the TimingDNA instance, not on module globals, so
# two accounts running in parallel can't clobber each other's delay / No-CD.
# ---------------------------------------------------------------------------

def test_two_dna_instances_have_independent_pacing():
    a = d.TimingDNA(111)
    b = d.TimingDNA(222)
    a.set_delay_config(turn_delay_min=3.0, turn_delay_max=5.0, disabled=False)
    b.set_delay_config(disabled=True)  # account B flips No-CD ON

    # B turning No-CD on must NOT disable A, and A's range must NOT leak into B.
    assert a.delays_disabled is False
    assert b.delays_disabled is True
    assert (a.turn_delay_min, a.turn_delay_max) == (3.0, 5.0)
    assert (b.turn_delay_min, b.turn_delay_max) == (d.TURN_DELAY_MIN, d.TURN_DELAY_MAX)


def test_set_delay_config_is_a_partial_update():
    dna = d.TimingDNA(5)
    dna.set_delay_config(turn_delay_min=1.0, turn_delay_max=2.0, disabled=False)
    dna.set_delay_config(disabled=True)  # only the flag changes
    assert dna.turn_delay_min == 1.0
    assert dna.turn_delay_max == 2.0
    assert dna.delays_disabled is True


def test_simulate_turn_delay_uses_instance_config():
    dna = d.TimingDNA(123)
    dna.set_delay_config(disabled=True)
    assert dna.simulate_turn_delay() == 0.0  # No-CD -> no pause

    dna.set_delay_config(disabled=False, turn_delay_min=0.0, turn_delay_max=0.0)
    assert dna.simulate_turn_delay() == 0.0  # zero range -> skipped

    dna.set_delay_config(turn_delay_min=0.01, turn_delay_max=0.02)
    dt = dna.simulate_turn_delay()
    assert 0.01 <= dt <= 0.02  # reads the instance range, not module globals


def test_default_dna_seeds_from_module_defaults():
    fresh = d.TimingDNA(999)
    assert fresh.delays_disabled == d.GLOBAL_DELAYS_DISABLED
    assert fresh.turn_delay_min == d.TURN_DELAY_MIN
    assert fresh.turn_delay_max == d.TURN_DELAY_MAX


def test_action_delay_uses_monotonic_elapsed_time(monkeypatch):
    dna = d.TimingDNA(1234)
    dna.set_delay_config(disabled=False)
    client = type("Client", (), {"_last_raw_call_ts": 50.0})()
    sleeps = []

    monkeypatch.setattr(dna, "_lognorm", lambda _mu, _sigma: 1.0)
    monkeypatch.setattr(dna, "_chance", lambda: 1.0)
    monkeypatch.setattr(d.time, "monotonic", lambda: 50.25)
    monkeypatch.setattr(
        d.time,
        "time",
        lambda: (_ for _ in ()).throw(AssertionError("wall clock read")),
    )
    monkeypatch.setattr(d.time, "sleep", sleeps.append)

    assert dna.simulate_delay("test_endpoint", client) == 0.8
    assert sleeps == [0.55]


# ---------------------------------------------------------------------------
# set_turn_delay / get_turn_delay are per-Session and push onto the live DNA.
# ---------------------------------------------------------------------------

def test_set_turn_delay_is_per_session():
    a = _make_session("delay-accA")
    b = _make_session("delay-accB")

    DelayConfigService().set_turn_delay(a, 3.0, 5.0, disabled=False)
    DelayConfigService().set_turn_delay(b, 0.0, 0.0, disabled=True)

    ga = DelayConfigService().get_turn_delay(a)
    gb = DelayConfigService().get_turn_delay(b)
    assert (ga["min"], ga["max"], ga["disabled"]) == (3.0, 5.0, False)
    assert gb["disabled"] is True
    # A is untouched by B's No-CD.
    assert ga["disabled"] is False


def test_apply_delay_to_dna_pushes_config_onto_live_dna():
    s = _make_session("delay-accC")
    dna = d.TimingDNA(424242)

    class FakeClient:
        pass

    fc = FakeClient()
    fc._dna = dna
    s.client = fc

    DelayConfigService().set_turn_delay(s, 2.0, 4.0, disabled=False)  # -> apply_delay_to_dna
    assert dna.delays_disabled is False
    assert (dna.turn_delay_min, dna.turn_delay_max) == (2.0, 4.0)

    DelayConfigService().set_turn_delay(s, 0, 0, disabled=True)
    assert dna.delays_disabled is True
