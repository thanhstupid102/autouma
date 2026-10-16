import os
from pathlib import Path
import subprocess
import sys


def _source_snapshot(source_root: Path) -> dict[str, tuple[int, int]]:
    snapshot = {}
    for current_root, dirnames, filenames in os.walk(source_root):
        dirnames[:] = [name for name in dirnames if name != ".git"]
        current = Path(current_root)
        for filename in filenames:
            path = current / filename
            result = path.stat()
            snapshot[path.relative_to(source_root).as_posix()] = (
                result.st_size,
                result.st_mtime_ns,
            )
    return snapshot


def test_importing_main_does_not_mutate_the_source_tree(tmp_path):
    source_root = Path(__file__).resolve().parents[1]
    cwd = tmp_path / "unrelated-cwd"
    cwd.mkdir()
    before = _source_snapshot(source_root)
    env = os.environ.copy()
    env.update({
        "PYTHONDONTWRITEBYTECODE": "1",
        "UMA_RUNTIME_DIR": str(tmp_path / "runtime"),
        "XDG_STATE_HOME": str(tmp_path / "xdg-state"),
        "XDG_DATA_HOME": str(tmp_path / "xdg-data"),
        "LOCALAPPDATA": str(tmp_path / "local-app-data"),
        "USERPROFILE": str(tmp_path / "user-profile"),
        "PYTHONPATH": os.pathsep.join(
            [str(source_root), env.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep),
    })
    env.pop("SWEEPY_SKIP_STARTUP_GEN", None)

    result = subprocess.run(
        [sys.executable, "-c", "from main import app"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert _source_snapshot(source_root) == before
