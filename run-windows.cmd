@echo off
setlocal
cd /d "%~dp0"

set "FORCE_UI=0"
set "SKIP_UI=0"
set "MAIN_ARGS="

:parse_launcher_args
if "%~1"=="" goto args_ready
if /I "%~1"=="--force-ui" (
    set "FORCE_UI=1"
    shift
    goto parse_launcher_args
)
if /I "%~1"=="--skip-ui" (
    set "SKIP_UI=1"
    shift
    goto parse_launcher_args
)
if "%~1"=="--" (
    shift
    goto collect_main_args
)

:collect_main_args
if "%~1"=="" goto args_ready
set "MAIN_ARGS=%MAIN_ARGS% "%~1""
shift
goto collect_main_args

:args_ready
if "%FORCE_UI%"=="1" if "%SKIP_UI%"=="1" (
    echo ERROR: --force-ui and --skip-ui cannot be used together. 1>&2
    exit /b 1
)

set "PYTHON_CMD="
where py.exe >nul 2>&1
if not errorlevel 1 (
    py -3.11 -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>&1
    if not errorlevel 1 set "PYTHON_CMD=py -3.11"
)
if not defined PYTHON_CMD (
    where py.exe >nul 2>&1
    if not errorlevel 1 (
        py -3 -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD=py -3"
    )
)
if not defined PYTHON_CMD (
    where python.exe >nul 2>&1
    if not errorlevel 1 (
        python -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>&1
        if not errorlevel 1 set "PYTHON_CMD=python"
    )
)
if not defined PYTHON_CMD (
    echo ERROR: Python 3.11 or newer is required. Install it and make it available through the py launcher or PATH. 1>&2
    exit /b 1
)

for /f "delims=" %%V in ('%PYTHON_CMD% -c "import platform; print(platform.python_version())"') do set "PYTHON_VERSION=%%V"
echo [1/5] Using Python %PYTHON_VERSION% via %PYTHON_CMD%

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [2/5] Creating .venv...
    %PYTHON_CMD% -m venv "%~dp0.venv"
    if errorlevel 1 (
        echo ERROR: Could not create .venv. Repair or reinstall Python with venv support and retry. 1>&2
        exit /b 1
    )
) else (
    echo [2/5] Reusing .venv.
)

"%VENV_PY%" -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>&1
if errorlevel 1 (
    echo ERROR: The existing .venv is not usable with Python 3.11+. Remove .venv and rerun this script. 1>&2
    exit /b 1
)

"%VENV_PY%" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo       Restoring pip in .venv...
    "%VENV_PY%" -m ensurepip --upgrade
    if errorlevel 1 (
        echo ERROR: pip is unavailable in .venv and could not be restored. Recreate .venv and retry. 1>&2
        exit /b 1
    )
)

"%VENV_PY%" -c "import sys; from importlib.metadata import distributions; from pathlib import Path; from pip._vendor.packaging.requirements import Requirement; from pip._vendor.packaging.utils import canonicalize_name; reqs=[Requirement(line) for raw in Path('requirements.txt').read_text(encoding='utf-8').splitlines() for line in [raw.split('#', 1)[0].strip()] if line]; reqs=[req for req in reqs if req.marker is None or req.marker.evaluate()]; installed={canonicalize_name(dist.metadata['Name']): dist.version for dist in distributions() if dist.metadata['Name']}; raise SystemExit(any(canonicalize_name(req.name) not in installed or (req.specifier and not req.specifier.contains(installed[canonicalize_name(req.name)], prereleases=True)) for req in reqs))" >nul 2>&1
if errorlevel 1 goto install_python_requirements
"%VENV_PY%" -m pip check >nul 2>&1
if errorlevel 1 goto install_python_requirements
echo       Python requirements are already satisfied.
goto python_requirements_ready

:install_python_requirements
echo       Installing Python requirements...
"%VENV_PY%" -m pip install --disable-pip-version-check --requirement requirements.txt
if errorlevel 1 (
    echo ERROR: Python dependency installation failed. Check the message above and your network connection. 1>&2
    exit /b 1
)
"%VENV_PY%" -m pip check
if errorlevel 1 (
    echo ERROR: The Python environment has incompatible or missing dependencies. 1>&2
    exit /b 1
)

:python_requirements_ready
echo [3/5] Checking Node.js and Steam runtime packages...
where node.exe >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js 20.19+ in the 20.x line, or Node.js 22.12+, is required. 1>&2
    exit /b 1
)
where npm.cmd >nul 2>&1
if errorlevel 1 (
    echo ERROR: npm.cmd was not found on PATH. Repair or reinstall Node.js and retry. 1>&2
    exit /b 1
)
node -e "const [major, minor] = process.versions.node.split('.').map(Number); const ok = (major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22; if (!ok) process.exit(1);"
if errorlevel 1 (
    echo ERROR: Node.js 20.19+ in the 20.x line, or Node.js 22.12+, is required. Detected: 1>&2
    node --version 1>&2
    exit /b 1
)

node -e "const fs = require('fs'); for (const name of ['steam-user', 'steam-session']) { const file = 'node_modules/' + name + '/package.json'; const pkg = JSON.parse(fs.readFileSync(file, 'utf8')); if (pkg.name !== name) process.exit(1); }" >nul 2>&1
if not errorlevel 1 goto node_runtime_ready
echo       Installing locked Steam runtime packages...
call npm.cmd ci --ignore-scripts --omit=dev
if errorlevel 1 (
    echo ERROR: Root Node dependency installation failed. Check npm's message and your network connection. 1>&2
    exit /b 1
)
node -e "const fs = require('fs'); for (const name of ['steam-user', 'steam-session']) { const file = 'node_modules/' + name + '/package.json'; const pkg = JSON.parse(fs.readFileSync(file, 'utf8')); if (pkg.name !== name) process.exit(1); }" >nul 2>&1
if errorlevel 1 (
    echo ERROR: npm completed, but steam-user or steam-session is still missing or invalid. 1>&2
    exit /b 1
)
goto node_runtime_done

:node_runtime_ready
echo       Steam runtime packages are already installed.

:node_runtime_done
echo [4/5] Checking the web UI build...
if "%SKIP_UI%"=="1" (
    echo       Skipping the UI build because --skip-ui was supplied.
    goto ui_ready
)
if "%FORCE_UI%"=="1" (
    echo       Rebuilding the UI because --force-ui was supplied...
    goto build_ui
)
"%VENV_PY%" -c "from pathlib import Path; output=Path('frontend/dist/index.html'); inputs=[Path('frontend/index.html'), Path('frontend/package.json'), Path('frontend/package-lock.json'), *Path('frontend/src').rglob('*'), *Path('frontend').glob('vite.config.*'), *Path('frontend').glob('tsconfig*.json')]; fresh=output.is_file() and all(not path.is_file() or path.stat().st_mtime_ns <= output.stat().st_mtime_ns for path in inputs); raise SystemExit(not fresh)" >nul 2>&1
if not errorlevel 1 (
    echo       frontend/dist/index.html is up to date; skipping the UI build.
    goto ui_ready
)
echo       Building the UI because it is missing or stale...

:build_ui
call npm.cmd --prefix frontend ci
if errorlevel 1 (
    echo ERROR: Frontend dependency installation failed. Check npm's message and your network connection. 1>&2
    exit /b 1
)
call npm.cmd --prefix frontend run build
if errorlevel 1 (
    echo ERROR: Frontend build failed. Check the build errors above. 1>&2
    exit /b 1
)
if not exist "%~dp0frontend\dist\index.html" (
    echo ERROR: The frontend build completed without producing frontend/dist/index.html. 1>&2
    exit /b 1
)

:ui_ready
echo [5/5] Starting ManhattanCafe with main.py...
"%VENV_PY%" main.py%MAIN_ARGS%
exit /b %errorlevel%
