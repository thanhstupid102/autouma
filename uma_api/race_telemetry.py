"""Race-out telemetry coordinate synthesis.

The real client reports where on the race-result screen the player tapped, in
``race_out``'s ``button_info`` field. This is *telemetry*, not an input event --
nothing is clicked, the numbers are only rendered into the payload. Use one
logical height on every host so the synthetic payload is independent of a
physical display; an explicit environment override intentionally gives up that
cross-host parity.
"""
import json
import logging
import os
import time

# Call-time forwarders into career_bot.delay (§13.2 B3): these draw from the
# account's TimingDNA -- same values, same draw order -- but importing this module
# (and therefore uma_api.client, which imports it) no longer imports the decision
# engine. No policy seam here on purpose: build_button_info is a module-level pure
# function with no client to inject into, and extracting race-out telemetry off the
# client is §13.1 A17's job, not B3's.
from uma_api.timing import dna_gauss, dna_uniform


log = logging.getLogger(__name__)

CANONICAL_LOGICAL_HEIGHT = 864
SCREEN_HEIGHT_OVERRIDE_ENV = "UMA_RACE_TELEMETRY_HEIGHT"


def screen_height():
    """Return the canonical logical height or its explicit environment override."""
    raw_value = os.environ.get(SCREEN_HEIGHT_OVERRIDE_ENV)
    if raw_value is None or not raw_value.strip():
        return CANONICAL_LOGICAL_HEIGHT

    try:
        value = int(raw_value.strip())
    except ValueError:
        value = 0
    if value < 16:
        log.warning(
            "%s must be an integer of at least 16; using canonical height %s",
            SCREEN_HEIGHT_OVERRIDE_ENV,
            CANONICAL_LOGICAL_HEIGHT,
        )
        return CANONICAL_LOGICAL_HEIGHT
    return value


def build_button_info(viewer_id, scenario_id):
    """Synthesize one race-out ``button_info`` record (all fields int)."""
    screen_h = screen_height()

    window_w = int(screen_h * 9 / 16)
    scale_factor = 1080 / window_w

    ref_x = max(844, min(1150, int(dna_gauss(991, 62))))
    ref_y = max(55, min(255, int(dna_gauss(144, 33))))

    physical_x = int(ref_x / scale_factor)
    physical_y = int(ref_y / scale_factor)

    click_x = int(physical_x * scale_factor * 10000)
    click_y = int(physical_y * scale_factor * 10000)

    click_ts = int(time.time() - dna_uniform(3.0, 4.5))
    return {
        "ViewerId": viewer_id,
        "DeviceId": 4,
        "ScenarioId": scenario_id,
        "ClickPosX": click_x,
        "ClickPosY": click_y,
        "ClickServerTime": click_ts
    }


def apply_race_out_button_info(payload, viewer_id, scenario_id):
    """Write a freshly synthesized ``button_info`` into a race_out payload."""
    btn = build_button_info(viewer_id, scenario_id)
    payload['button_info'] = json.dumps(btn, separators=(',', ':'))
    return payload
