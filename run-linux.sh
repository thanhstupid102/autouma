#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$SCRIPT_DIR"

die() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

force_ui=0
skip_ui=0
while (($#)); do
    case "$1" in
        --force-ui)
            force_ui=1
            shift
            ;;
        --skip-ui)
            skip_ui=1
            shift
            ;;
        --)
            shift
            break
            ;;
        *)
            break
            ;;
    esac
done

if ((force_ui && skip_ui)); then
    die "--force-ui and --skip-ui cannot be used together."
fi

base_python=""
for candidate in python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 \
        && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' \
            >/dev/null 2>&1; then
        base_python="$(command -v "$candidate")"
        break
    fi
done

if [[ -z "$base_python" ]]; then
    die "Python 3.11 or newer is required. Install it and ensure python3 is on PATH."
fi

python_version="$("$base_python" -c 'import platform; print(platform.python_version())')"
printf '[1/5] Using Python %s at %s\n' "$python_version" "$base_python"

venv_python="$SCRIPT_DIR/.venv/bin/python"
if [[ ! -x "$venv_python" ]]; then
    printf '[2/5] Creating .venv...\n'
    if ! "$base_python" -m venv "$SCRIPT_DIR/.venv"; then
        die "Could not create .venv. Install the Python venv package (for example, python3-venv) and retry."
    fi
else
    printf '[2/5] Reusing .venv.\n'
fi

if ! "$venv_python" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' \
    >/dev/null 2>&1; then
    die "The existing .venv is not usable with Python 3.11+. Remove .venv and rerun this script."
fi

if ! "$venv_python" -m pip --version >/dev/null 2>&1; then
    printf '      Restoring pip in .venv...\n'
    if ! "$venv_python" -m ensurepip --upgrade; then
        die "pip is unavailable in .venv and could not be restored. Recreate .venv and retry."
    fi
fi

python_requirements_satisfied() {
    "$venv_python" - "$SCRIPT_DIR/requirements.txt" <<'PY'
from importlib.metadata import distributions
from pathlib import Path
import sys

from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.utils import canonicalize_name

requirements_path = Path(sys.argv[1])
requirements = []
for raw_line in requirements_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.split("#", 1)[0].strip()
    if line:
        requirement = Requirement(line)
        if requirement.marker is None or requirement.marker.evaluate():
            requirements.append(requirement)

installed = {
    canonicalize_name(distribution.metadata["Name"]): distribution.version
    for distribution in distributions()
    if distribution.metadata["Name"]
}
for requirement in requirements:
    installed_version = installed.get(canonicalize_name(requirement.name))
    if installed_version is None:
        raise SystemExit(1)
    if requirement.specifier and not requirement.specifier.contains(
        installed_version,
        prereleases=True,
    ):
        raise SystemExit(1)
PY
}

if python_requirements_satisfied 2>/dev/null \
    && "$venv_python" -m pip check >/dev/null 2>&1; then
    printf '      Python requirements are already satisfied.\n'
else
    printf '      Installing Python requirements...\n'
    if ! "$venv_python" -m pip install --disable-pip-version-check \
        --requirement "$SCRIPT_DIR/requirements.txt"; then
        die "Python dependency installation failed. Check the message above and your network connection."
    fi
    if ! "$venv_python" -m pip check; then
        die "The Python environment has incompatible or missing dependencies."
    fi
fi

printf '[3/5] Checking Node.js and Steam runtime packages...\n'
command -v node >/dev/null 2>&1 \
    || die "Node.js is required. Install Node.js ^20.19.0 or >=22.12.0 and retry."
command -v npm >/dev/null 2>&1 \
    || die "npm is required but was not found on PATH. Reinstall Node.js and retry."

if ! node -e "const [major, minor] = process.versions.node.split('.').map(Number); const ok = (major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22; if (!ok) process.exit(1);"; then
    node_version="$(node --version 2>/dev/null || printf 'unknown')"
    die "Node.js ^20.19.0 or >=22.12.0 is required; found $node_version."
fi

node_runtime_ready() {
    node -e "const fs = require('fs'); for (const name of ['steam-user', 'steam-session']) { const file = 'node_modules/' + name + '/package.json'; const pkg = JSON.parse(fs.readFileSync(file, 'utf8')); if (pkg.name !== name) process.exit(1); }" \
        >/dev/null 2>&1
}

if node_runtime_ready; then
    printf '      Steam runtime packages are already installed.\n'
else
    printf '      Installing locked Steam runtime packages...\n'
    if ! npm ci --ignore-scripts --omit=dev; then
        die "Root Node dependency installation failed. Check npm's message and your network connection."
    fi
    node_runtime_ready \
        || die "npm completed, but steam-user or steam-session is still missing or invalid."
fi

ui_is_fresh() {
    "$venv_python" - <<'PY'
from pathlib import Path

output = Path("frontend/dist/index.html")
inputs = [
    Path("frontend/index.html"),
    Path("frontend/package.json"),
    Path("frontend/package-lock.json"),
]
inputs.extend(Path("frontend/src").rglob("*"))
inputs.extend(Path("frontend").glob("vite.config.*"))
inputs.extend(Path("frontend").glob("tsconfig*.json"))

if not output.is_file():
    raise SystemExit(1)

output_mtime = output.stat().st_mtime_ns
if any(path.is_file() and path.stat().st_mtime_ns > output_mtime for path in inputs):
    raise SystemExit(1)
PY
}

printf '[4/5] Checking the web UI build...\n'
if ((skip_ui)); then
    printf '      Skipping the UI build because --skip-ui was supplied.\n'
elif ((force_ui)) || ! ui_is_fresh; then
    if ((force_ui)); then
        printf '      Rebuilding the UI because --force-ui was supplied...\n'
    else
        printf '      Building the UI because it is missing or stale...\n'
    fi
    if ! npm --prefix frontend ci; then
        die "Frontend dependency installation failed. Check npm's message and your network connection."
    fi
    if ! npm --prefix frontend run build; then
        die "Frontend build failed. Check the build errors above."
    fi
    [[ -f "$SCRIPT_DIR/frontend/dist/index.html" ]] \
        || die "The frontend build completed without producing frontend/dist/index.html."
else
    printf '      frontend/dist/index.html is up to date; skipping the UI build.\n'
fi

printf '[5/5] Starting ManhattanCafe with main.py...\n'
exec "$venv_python" "$SCRIPT_DIR/main.py" "$@"
