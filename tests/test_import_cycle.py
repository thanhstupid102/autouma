"""Pins the app-layer import order acyclic (REFACTOR_PLAN.md 13.1/A1, §11 Phase 6).

Originally this guarded a real cycle: `uma_app/app.py` imported
`backend.app.routers` while every backend controller imported `uma_app.context`,
so merely importing `backend.app.routers` blew up with "cannot import name
'NormalRouter' from partially initialized module". §11 Phase 6 removed the cycle
structurally by folding `uma_app` into `backend/app/` with `context.py` +
`domain/` BELOW `routers/`. These cases pin that ordering so it cannot regress.

Each case runs in a FRESH interpreter (-B, no bytecode cache): an import-order
failure only reproduces on a cold import in that specific order, so importing
inside this process would prove nothing.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _fresh_import(statement):
    return subprocess.run(
        [sys.executable, "-B", "-c", statement],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )


def test_backend_routers_imports_standalone():
    result = _fresh_import("import backend.app.routers; print(backend.app.routers.NormalRouter.__name__)")
    assert result.returncode == 0, f"cold `import backend.app.routers` failed:\n{result.stderr}"
    assert "NormalRouter" in result.stdout


def test_app_layer_below_routers_does_not_import_upward():
    # §11 Phase 6: context + domain/ sit BELOW routers. Importing either must NOT
    # drag in the routers or the app factory -- that upward edge WAS the cycle.
    result = _fresh_import(
        "import sys, backend.app.context, backend.app.domain.account_status, "
        "backend.app.domain.career_selection, backend.app.domain.preset_runtime, "
        "backend.app.domain.account_store, backend.app.domain.rank_point; "
        "print('backend.app.app' in sys.modules, 'backend.app.routers' in sys.modules)"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False False"


def test_create_app_imports_cold():
    # main.py's entrypoint import. Before Phase 6 this only worked through a lazy
    # PEP 562 __getattr__ on uma_app/__init__.py; now it is a plain import.
    result = _fresh_import("from backend.app.app import create_app; print(callable(create_app))")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"


def test_uma_api_session_does_not_import_fastapi():
    # §13.1 B2 first step: the get_session FastAPI dependency moved to
    # backend/app/deps.py, so importing the transport-side session module must
    # no longer drag the web framework into the process.
    result = _fresh_import(
        "import sys, uma_api.session; print('fastapi' in sys.modules)"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_uma_api_session_does_not_import_career_bot():
    # §13.2 B2 step 2: CareerRunner construction and the delay defaults are
    # call-time imports now — importing the transport session module must not
    # drag the decision engine in. Constructing a Session still binds it
    # (pinned from the other side by the two tests below).
    result = _fresh_import(
        "import sys, uma_api.session; print(any(m == 'career_bot' or m.startswith('career_bot.') for m in sys.modules))"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_uma_api_session_does_not_import_the_application_layer():
    # §13.2 B2 final step: the runner/loop state moved OUT of the transport
    # Session into backend/app/runner_state.py. The transport module reaches it
    # through a call-time import, so importing uma_api.session must not pull the
    # application layer (nor, transitively, fastapi/career_bot) into the process.
    result = _fresh_import(
        "import sys, uma_api.session; "
        "print(any(m == 'backend' or m.startswith('backend.') for m in sys.modules))"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_constructing_a_session_still_binds_the_runner_engine():
    # The other half of the pin, and the reason the two "does not import" tests
    # above are not satisfiable by simply breaking the runner: CONSTRUCTING a
    # Session must still bind an application-owned runtime with a real
    # CareerRunner, at construction time (no lifecycle-order change).
    result = _fresh_import(
        "import sys, uma_api.session; "
        "from backend.app.runner_state import peek_career_runtime; "
        "s = uma_api.session.Session(name='import-cycle-pin'); "
        "rt = peek_career_runtime(s); "
        "print(rt is not None, "
        "type(rt.runner).__name__, "
        "'career_bot.engine' in sys.modules)"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True CareerRunner True"
