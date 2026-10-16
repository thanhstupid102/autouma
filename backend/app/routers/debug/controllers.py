from fastapi import APIRouter, Depends

from backend.app.schemas.envelope import ApiResponse
from backend.app.deps import get_session
from uma_api.session import Session
from uma_api import game_service
from backend.app.context import AppContext, get_ctx


router = APIRouter(
    prefix="/debug",
    tags=["debugs"],
    responses={404: {"description": "Not found"}},
)


@router.get(
    "/start-state",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def get_start_state(session: Session = Depends(get_session)):
    return {"success": True, **session.start_state}


@router.get(
    "/raw-load",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def get_raw_load(
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    record = game_service.load_index_cached(ctx.state_root, session.name)
    if record is None:
        return {"success": False, "detail": "No cached load/index response", "endpoint": "load/index"}
    return {"success": True, **record}
