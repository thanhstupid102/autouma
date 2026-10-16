from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from backend.app.context import AppContext, get_ctx


# The SPA is served at the ROOT ("/" and "/{full_path:path}"), not under /api,
# so this router carries full literal paths and is included with an empty
# prefix -- see backend/app/routers/__init__.py. Its catch-all route must be
# registered LAST of all routers (after every other domain router and after
# the /static mount), or it will shadow every other path in the app.
router = APIRouter(
    tags=["others"],
    responses={404: {"description": "Not found"}},
)


@router.get("/", response_class=HTMLResponse)
async def root(ctx: AppContext = Depends(get_ctx)):
    new_index = ctx.frontend_dist / "index.html"
    if new_index.exists():
        return FileResponse(new_index, media_type="text/html", headers={"Cache-Control": "no-cache"})
    return (
        "Dashboard not built. Stop the server and rerun the platform launcher "
        "with --force-ui."
    )


# SPA history fallback: client-side routes (/account/:name, /setup, /library, ...)
# have no server route, so a direct load or refresh would 404. Serve index.html for
# any unmatched non-API GET so react-router can handle it. Registered last, so every
# explicit route and the /static mount take precedence.
@router.get("/{full_path:path}", response_class=HTMLResponse)
async def spa_fallback(full_path: str, ctx: AppContext = Depends(get_ctx)):
    # Unmatched /api/* is a genuine 404 — keep it JSON, don't serve the SPA shell.
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    # Serve a real built asset if one exists (favicon.svg, icons.svg, ...),
    # guarding against path traversal outside the dist directory.
    if full_path:
        try:
            asset = (ctx.frontend_dist / full_path).resolve()
            if asset.is_file() and ctx.frontend_dist.resolve() in asset.parents:
                return FileResponse(asset, headers={"Cache-Control": "no-cache"})
        # `full_path` is untrusted URL text: resolve()/is_file() reject it with
        # OSError (invalid name/too long) or ValueError (embedded null byte).
        except (OSError, ValueError):
            pass
    # Otherwise it's a client-side route → serve the SPA shell.
    new_index = ctx.frontend_dist / "index.html"
    if new_index.exists():
        return FileResponse(new_index, media_type="text/html", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="Not Found")
