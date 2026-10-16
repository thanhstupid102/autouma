import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _time_calls(relative_path, function_name):
    path = ROOT / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    ]
    assert functions
    return {
        node.func.attr
        for function in functions
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "time"
    }


def test_elapsed_duration_sites_use_monotonic_time():
    duration_sites = (
        ("uma_api/client.py", "_call_locked"),
        ("uma_api/client.py", "_note_api_error"),
        ("career_bot/delay.py", "simulate_delay"),
        ("career_bot/engine/reporting.py", "_flush_report"),
    )

    for path, function_name in duration_sites:
        calls = _time_calls(path, function_name)
        assert "monotonic" in calls, f"{path}:{function_name} is not monotonic"
        assert "time" not in calls, f"{path}:{function_name} reads wall-clock time"


def test_persisted_and_server_timestamp_sites_keep_wall_clock_time():
    wall_clock_sites = (
        ("uma_api/api_warehouse.py", "write_latest"),
        ("uma_api/race_telemetry.py", "build_button_info"),
        ("uma_api/trace.py", "write"),
        ("uma_data/tp_cost.py", "single_mode_career_start_tp"),
        ("uma_data/master_updater.py", "_resolve_root_url"),
    )

    for path, function_name in wall_clock_sites:
        assert "time" in _time_calls(path, function_name), (
            f"{path}:{function_name} must keep a transferable wall-clock timestamp"
        )
