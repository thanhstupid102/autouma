import re
from pathlib import Path, PurePosixPath

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_REQUIRED_PATHS = (
    "scripts/scrape_gametora_effects.py",
    "data/bot_config/default.json",
    "data/json/event_prefs.json",
    "assets/data/uma_race_data.json",
    "main.py",
    "core/__init__.py",
    "core/settings.py",
    "core/runtime_paths.py",
    "core/operational_time.py",
    "requirements.txt",
)


def _dockerignore_patterns(text: str) -> list[tuple[bool, str]]:
    patterns = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        pattern = line[1:] if negated else line
        pattern = pattern.replace("\\", "/").strip("/")
        if pattern and pattern != ".":
            patterns.append((negated, pattern))
    return patterns


def _glob_regex(pattern: str) -> re.Pattern[str]:
    result = []
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if character == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 1
                if index + 1 < len(pattern) and pattern[index + 1] == "/":
                    index += 1
                    result.append("(?:.*/)?")
                else:
                    result.append(".*")
            else:
                result.append("[^/]*")
        elif character == "?":
            result.append("[^/]")
        else:
            result.append(re.escape(character))
        index += 1
    return re.compile("^" + "".join(result) + "$")


def _pattern_matches(candidate: str, pattern: str) -> bool:
    if "/" not in pattern:
        return _glob_regex(pattern).match(PurePosixPath(candidate).name) is not None
    return _glob_regex(pattern).match(candidate) is not None


def _is_ignored(path: str, patterns: list[tuple[bool, str]]) -> bool:
    normalized = PurePosixPath(path).as_posix().lstrip("./")
    parts = normalized.split("/")
    candidates = ["/".join(parts[:index]) for index in range(1, len(parts) + 1)]
    excluded = {candidate: False for candidate in candidates}

    for negated, pattern in patterns:
        for candidate in candidates:
            if _pattern_matches(candidate, pattern):
                excluded[candidate] = not negated

    # Docker cannot re-include a file while one of its parent directories
    # remains excluded, so every candidate in the path must be included.
    return any(excluded.values())


@pytest.mark.parametrize("runtime_path", RUNTIME_REQUIRED_PATHS)
def test_dockerignore_keeps_runtime_required_paths(runtime_path):
    patterns = _dockerignore_patterns(
        (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
    )

    assert not _is_ignored(runtime_path, patterns), (
        f"{runtime_path} is required at runtime but is excluded by .dockerignore"
    )


def test_dockerfile_never_installs_reverse_engineering_requirements():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "requirements-re.txt" not in dockerfile


def test_container_identity_uses_manhattancafe_names_and_numeric_ids():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (REPO_ROOT / "compose.yaml").read_text(encoding="utf-8")
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "ARG APP_UID=10001" in dockerfile
    assert "ARG APP_GID=10001" in dockerfile
    assert 'groupadd --gid "${APP_GID}" manhattancafe' in dockerfile
    assert "--home-dir /state --no-create-home" in dockerfile
    assert "--shell /usr/sbin/nologin manhattancafe" in dockerfile
    assert "services:\n  manhattancafe:" in compose
    assert "image: manhattancafe-uma-auto" in compose
    assert "name: manhattancafe-uma-state" in compose
    assert "docker build --tag manhattancafe-uma-auto:ci" in workflow


def test_dockerignore_matcher_honors_later_negations():
    runtime_path = "scripts/scrape_gametora_effects.py"

    assert not _is_ignored(
        runtime_path,
        _dockerignore_patterns("scripts/\n!scripts/\n"),
    )
    assert _is_ignored(
        runtime_path,
        _dockerignore_patterns("!scripts/\nscripts/\n"),
    )
