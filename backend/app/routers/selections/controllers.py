from fastapi import APIRouter, Depends

from backend.app.schemas.envelope import ApiResponse
from backend.app.deps import get_session
from uma_api.session import Session
from backend.app.context import get_ctx, AppContext

from .schemas.selection import UISelectionRequest
from .services.selection_service import SelectionService


router = APIRouter(
    prefix="",
    tags=["selections"],
    responses={404: {"description": "Not found"}},
)


@router.post(
    "/selection",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def api_update_selection(
    payload: UISelectionRequest,
    session: Session = Depends(get_session),
    ctx: AppContext = Depends(get_ctx),
):
    return SelectionService(session, ctx).update(payload.selection)
