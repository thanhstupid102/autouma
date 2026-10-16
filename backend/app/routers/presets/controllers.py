from fastapi import APIRouter, Depends

from backend.app.schemas.envelope import ApiResponse
from backend.app.context import get_ctx, AppContext

from .schemas.preset import (
    SaveRacesRequest,
    SavePresetRequest,
)
from .services.preset_service import PresetService


router = APIRouter(
    prefix="/presets",
    tags=["presets"],
    responses={404: {"description": "Not found"}},
)


@router.get(
    "",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def api_get_presets(
    kind: str = "skill",
    ctx: AppContext = Depends(get_ctx),
):
    return PresetService(ctx, kind).get_all()


@router.post(
    "",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def api_save_preset(
    payload: SavePresetRequest,
    kind: str = "skill",
    ctx: AppContext = Depends(get_ctx),
):
    return PresetService(ctx, kind).save(payload.preset)


@router.delete(
    "/{name}",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def api_delete_preset(
    name: str,
    kind: str = "skill",
    ctx: AppContext = Depends(get_ctx),
):
    return PresetService(ctx, kind).delete(name)


@router.put(
    "/{name}/races",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def api_save_preset_races(
    name: str,
    payload: SaveRacesRequest,
    kind: str = "skill",
    ctx: AppContext = Depends(get_ctx),
):
    return PresetService(ctx, kind).save_races(name, payload.races)
