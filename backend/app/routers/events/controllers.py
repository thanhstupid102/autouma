from fastapi import APIRouter, Depends

from backend.app.schemas.envelope import ApiResponse
from backend.app.context import get_ctx, AppContext

from .schemas.event import EventPrefsRequest
from .services.event_service import EventService


router = APIRouter(
    prefix="/events",
    tags=["events"],
    responses={404: {"description": "Not found"}},
)


@router.get(
    "/catalog",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def get_event_catalog(ctx: AppContext = Depends(get_ctx)):
    return EventService(ctx).get_catalog()


@router.post(
    "/catalog/rebuild",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def rebuild_event_catalog(ctx: AppContext = Depends(get_ctx)):
    return EventService(ctx).rebuild()


@router.post(
    "/catalog/refresh",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def update_event_database(ctx: AppContext = Depends(get_ctx)):
    return await EventService(ctx).update_database()


@router.get(
    "/prefs",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def get_event_prefs(ctx: AppContext = Depends(get_ctx)):
    return EventService(ctx).get_prefs()


@router.post(
    "/prefs",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def set_event_prefs(
    req: EventPrefsRequest,
    ctx: AppContext = Depends(get_ctx),
):
    return EventService(ctx).set_prefs(req.prefs)
