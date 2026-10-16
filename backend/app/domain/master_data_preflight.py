from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypedDict

from career_bot.scenarios import get_strategy_class
from core.runtime_paths import resolve_state_root, state_paths_for
import uma_data


class _Requirement(TypedDict):
    label: str
    loader: str
    tables: tuple[str, ...]


_SCENARIO_REQUIREMENTS: dict[int, tuple[_Requirement, ...]] = {
    2: (
        {
            "label": "mandatory route objectives",
            "loader": "load_route_race_objectives",
            "tables": ("single_mode_race_group", "single_mode_route_race"),
        },
        {
            "label": "Unity Cup scout aptitudes",
            "loader": "load_scout_aptitudes",
            "tables": ("single_mode_scout_chara",),
        },
    ),
}


def _scenario_label(scenario_id: int) -> str:
    strategy = get_strategy_class(scenario_id)
    if strategy is not None:
        return str(strategy.display_label)
    return f"scenario {scenario_id}"


def _dependency_failures(base_dir: Path, scenario_id: int) -> list[dict[str, Any]]:
    failures = []
    for requirement in _SCENARIO_REQUIREMENTS.get(scenario_id, ()):
        loader = getattr(uma_data, requirement["loader"])
        try:
            result = loader(base_dir)
        except Exception as exc:
            failures.append({
                **requirement,
                "reason": "validation_error",
                "detail": str(exc),
            })
            continue

        # Consumer tests commonly inject the useful payload only. Treat an
        # explicit failure as unavailable while preserving that established seam.
        if not isinstance(result, Mapping) or result.get("success") is False:
            failure: dict[str, Any] = dict(requirement)
            if isinstance(result, Mapping):
                failure.update({
                    "reason": result.get("reason") or "missing_tables",
                    "detail": result.get("detail"),
                    "master_mdb_path": result.get("master_mdb_path"),
                    "missing_tables": result.get("missing_tables"),
                })
            else:
                failure.update({
                    "reason": "validation_error",
                    "detail": "loader returned a non-object result",
                })
            failures.append(failure)
    return failures


def _stale_generated_json_paths(base_dir: Path, state_root: Path) -> list[Path]:
    output_dir = state_paths_for(base_dir, state_root).master_json_dir
    stale_paths = []
    for filename in uma_data.stale_master_json_files(base_dir, state_root):
        path = output_dir / str(filename)
        try:
            # Missing generated output deliberately falls back to the shipped
            # seed. A present stale file shadows that seed and must not be used.
            if path.is_file():
                stale_paths.append(path)
        except OSError:
            stale_paths.append(path)
    return stale_paths


def career_master_data_error(base_dir, state_root, scenario_id) -> str | None:
    """Return the actionable career-start blocker, or None when data is usable."""
    source_root = Path(base_dir).resolve()
    runtime_root = (
        Path(state_root).resolve()
        if state_root is not None
        else resolve_state_root(source_root).root
    )
    sid = int(scenario_id or 0)
    scenario = _scenario_label(sid)
    failures = _dependency_failures(source_root, sid)

    missing_db = next(
        (failure for failure in failures if failure.get("reason") == "missing_db"),
        None,
    )
    if missing_db is not None:
        db_path = missing_db.get("master_mdb_path") or uma_data.configured_master_mdb_path(source_root)
        return (
            f"Career start blocked for {scenario}: master.mdb is unavailable at {db_path}. "
            "master.mdb is fetched automatically; check outbound network access and "
            "the pre-download resource version, then restart or log in to retry the CDN fetch."
        )

    missing_table_failures = [
        failure for failure in failures
        if failure.get("reason") == "missing_tables"
    ]
    if missing_table_failures:
        missing_tables: set[str] = set()
        for failure in missing_table_failures:
            reported = failure.get("missing_tables") or failure["tables"]
            missing_tables.update(str(table) for table in reported)
        db_path = (
            missing_table_failures[0].get("master_mdb_path")
            or uma_data.configured_master_mdb_path(source_root)
        )
        names = ", ".join(sorted(missing_tables))
        return (
            f"Career start blocked for {scenario}: master.mdb at {db_path} is missing "
            f"required table(s): {names}. Move the incomplete database aside, then restart "
            "or log in so the automatic CDN fetch replaces it; if the fetch fails, check "
            "network access and the resolved resource version."
        )

    if failures:
        labels = ", ".join(str(failure["label"]) for failure in failures)
        detail = "; ".join(
            str(failure.get("detail") or "unknown validation failure")
            for failure in failures
        )
        return (
            f"Career start blocked for {scenario}: required master data could not be "
            f"validated ({labels}): {detail}. Check master.mdb, then restart or log in "
            "to retry the automatic refresh."
        )

    stale_paths = _stale_generated_json_paths(source_root, runtime_root)
    if stale_paths:
        names = ", ".join(str(path) for path in stale_paths)
        return (
            f"Career start blocked: generated master JSON does not match master.mdb: {names}. "
            f"Run `python scripts/generate_master_data.py` from {source_root} to regenerate "
            "the files, then retry."
        )
    return None
