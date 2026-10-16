import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from backend.app.context import AppContext, get_ctx


# Image ids are flat tokens (786 numeric names ship today). Must stay in step with
# the ungated-path pattern in backend/app/api_auth.py.
_SAFE_IMAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


# Paths here are a deliberate mix of "/api/..." and bare-root paths (legacy
# behaviour, preserved verbatim), so this router carries full literal paths
# and is included with an empty prefix -- see backend/app/routers/__init__.py.
router = APIRouter(
    tags=["assets"],
    responses={404: {"description": "Not found"}},
)


def _resolve_asset_file(base_dir, file_name, detail):
    base_path = base_dir.resolve()
    try:
        path = (base_path / file_name).resolve()
        path.relative_to(base_path)
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(status_code=404, detail=detail) from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail=detail)
    return path


@router.get("/api/images/{image_name}")
async def get_image(image_name: str, ctx: AppContext = Depends(get_ctx)):
    name_no_ext = image_name.split('?')[0].replace('.png', '')

    # This route is deliberately reachable without an API token (shipped artwork,
    # requested by <img> tags that cannot send a header), so the name must not be
    # able to address anything outside the images directory. Ids are flat tokens;
    # reject separators and dot-segments outright rather than relying on the
    # router refusing to match them.
    if not _SAFE_IMAGE_NAME.match(name_no_ext):
        raise HTTPException(status_code=404, detail="Image not found")

    exact_path = ctx.images_dir / f"{name_no_ext}.png"
    if exact_path.exists():
        return FileResponse(exact_path, media_type="image/png", headers={"Cache-Control": "no-cache"})

    for fallback_id in ['100101', '10010', '10000', '10001']:
        fb_path = ctx.images_dir / f"{fallback_id}.png"
        if fb_path.exists():
            return FileResponse(fb_path, media_type="image/png", headers={"Cache-Control": "no-cache"})

    raise HTTPException(status_code=404, detail="Image not found")


@router.get("/sweep.png")
async def sweep_png(ctx: AppContext = Depends(get_ctx)):
    path = ctx.base_dir / "assets" / "sweep.png"
    if path.exists():
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="sweep.png not found")


@router.get("/broom.png")
async def broom_png(ctx: AppContext = Depends(get_ctx)):
    path = ctx.base_dir / "assets" / "broom.png"
    if path.exists():
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="broom.png not found")


@router.get("/assets/data/{file_name}")
async def get_asset_data(file_name: str, ctx: AppContext = Depends(get_ctx)):
    path = _resolve_asset_file(
        ctx.base_dir / 'assets' / 'data', file_name, "File not found",
    )
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@router.get("/races/{file_name}")
async def get_race_image(file_name: str, ctx: AppContext = Depends(get_ctx)):
    path = _resolve_asset_file(
        ctx.base_dir / "assets" / "races", file_name, "Race image not found",
    )
    return FileResponse(path, headers={"Cache-Control": "max-age=31536000"})
