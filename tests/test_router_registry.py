import importlib
import pkgutil
from pathlib import Path

import backend.app.routers as router_package
from backend.app.routers import (
    _API_ROUTERS,
    assets_router,
    others_router,
)


def _discover_controller_routers():
    package_names = {
        module_info.name
        for module_info in pkgutil.iter_modules(router_package.__path__)
        if module_info.ispkg
    }

    # Domain directories are namespace packages, which pkgutil does not list.
    for package_root in map(Path, router_package.__path__):
        package_names.update(
            path.name
            for path in package_root.iterdir()
            if path.is_dir() and (path / "controllers.py").is_file()
        )

    discovered = {}
    for name in sorted(package_names):
        module = importlib.import_module(
            f"backend.app.routers.{name}.controllers"
        )
        router = getattr(module, "router", None)
        if router is not None:
            discovered[name] = router
    return discovered


def test_every_controller_router_is_registered():
    discovered = _discover_controller_routers()
    registered_ids = {
        id(router)
        for router in (*_API_ROUTERS, assets_router, others_router)
    }
    missing = sorted(
        name
        for name, router in discovered.items()
        if id(router) not in registered_ids
    )

    assert not missing, f"Unregistered controller routers: {', '.join(missing)}"


def test_no_stale_registry_entry():
    discovered_ids = {id(router) for router in _discover_controller_routers().values()}

    assert all(id(router) in discovered_ids for router in _API_ROUTERS)
