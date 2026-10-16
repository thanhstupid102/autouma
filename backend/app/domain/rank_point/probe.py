import json
import logging

from datetime import datetime, timezone
from pathlib import Path

from uma_api import game_service
from uma_api.errors import api_error_result_code
from core.runtime_paths import append_private_text

import backend.app.domain.rank_point as rp


log = logging.getLogger(__name__)


def _rankpoint_probe_log_path():
    if rp.RANKPOINT_PROBE_LOG_PATH is not None:
        return Path(rp.RANKPOINT_PROBE_LOG_PATH)
    return Path(rp.state_root) / "rankpoint_probes.jsonl"


def persist_rankpoint_probe(req, components, accepted_value, probe_count):
    p1 = components["parent_1"]
    p2 = components["parent_2"]
    rental = components["rental"]
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "card_id": int(req.card_id),
        "parent_1_id": p1["trained_chara_id"],
        "parent_1_card_id": p1["card_id"],
        "parent_2_id": p2["trained_chara_id"],
        "requested_parent_2_id": p2["requested_trained_chara_id"],
        "parent_2_card_id": p2["card_id"],
        "rental_viewer_id": rental["viewer_id"],
        "rental_trained_chara_id": rental["trained_chara_id"],
        "computed_value": components["computed"],
        "accepted_value": int(accepted_value),
        "delta": int(accepted_value) - components["computed"],
        "probe_count": int(probe_count),
        "components": {
            "relation_pairs": dict(components["relation_pairs"]),
            "relation_triples": dict(components["relation_triples"]),
            "relation_total": components["relation_total"],
            "g1_bonuses": {
                "parent_1": p1["g1_bonus"],
                "parent_2": p2["g1_bonus"],
                "parent_1_to_parent_2": components["parent_pair_g1_bonus"],
            },
            "g1_bonus_total": components["g1_bonus_total"],
            "formula_total": components["formula_total"],
            "used_account_fallback": components["used_account_fallback"],
        },
    }
    path = rp._rankpoint_probe_log_path()
    try:
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with rp.rank_point_probe_log_lock:
            append_private_text(path, line)
        return True
    except OSError as exc:
        log.warning(f"[RANKPOINT] failed to persist accepted probe: {exc}")
        return False


def probe_succession_rank_point(session, req, components, start_probe):
    """Bound and binary-search an exact server rank point after confirmed start/load 102s."""
    computed = int(components["computed"])
    lo = computed + 1
    hi = None
    probes = 0

    def attempt(candidate):
        nonlocal probes
        if probes >= rp.RANKPOINT_PROBE_MAX_ATTEMPTS:
            return "exhausted", None
        rp.dna_sleep(3.5, 5.0)
        game_service.reset_circuit(session)
        probes += 1
        log.info(
            f"[RANKPOINT] probe {probes}/{rp.RANKPOINT_PROBE_MAX_ATTEMPTS}: {candidate}"
        )
        try:
            return "accepted", start_probe(candidate)
        except Exception as probe_err:
            code = api_error_result_code(probe_err)
            if code == 102:
                return "low", None
            if code == 1052:
                return "high", None
            log.warning(
                f"[RANKPOINT] probe aborted at {candidate}: non-directional error "
                f"{code if code is not None else type(probe_err).__name__}: {probe_err}"
            )
            return "abort", None

    def accepted(candidate, result):
        delta = candidate - computed
        rental = components["rental"]
        log.info(
            f"[RANKPOINT] server accepted {candidate} (computed {computed}, delta {delta}) "
            f"for card={req.card_id} p1={req.parent_id_1} p2={req.parent_id_2} "
            f"rental={rental['viewer_id']}:{rental['trained_chara_id']}"
        )
        rp.persist_rankpoint_probe(req, components, candidate, probes)
        return result

    log.info(
        f"[RANKPOINT] confirmed no existing career; searching above computed {computed}"
    )
    for offset in rp.RANKPOINT_PROBE_OFFSETS:
        candidate = computed + offset
        outcome, result = attempt(candidate)
        if outcome == "accepted":
            return accepted(candidate, result)
        if outcome == "low":
            lo = candidate + 1
            continue
        if outcome == "high":
            hi = candidate - 1
            break
        if outcome == "exhausted":
            log.warning(
                f"[RANKPOINT] probe exhausted {rp.RANKPOINT_PROBE_MAX_ATTEMPTS}-attempt cap"
            )
        return None

    if hi is None:
        log.warning(
            f"[RANKPOINT] unable to bound accepted value by {computed + 4096}; giving up"
        )
        return None

    while lo <= hi:
        candidate = (lo + hi) // 2
        outcome, result = attempt(candidate)
        if outcome == "accepted":
            return accepted(candidate, result)
        if outcome == "low":
            lo = candidate + 1
            continue
        if outcome == "high":
            hi = candidate - 1
            continue
        if outcome == "exhausted":
            log.warning(
                f"[RANKPOINT] probe exhausted {rp.RANKPOINT_PROBE_MAX_ATTEMPTS}-attempt cap"
            )
        return None

    log.warning("[RANKPOINT] directional search ended without an exact value; giving up")
    return None
