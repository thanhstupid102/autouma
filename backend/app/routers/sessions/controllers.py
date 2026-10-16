from fastapi import APIRouter, Depends

from backend.app.schemas.envelope import ApiResponse
from backend.app.deps import get_session
from uma_api.session import Session

from .services.session_service import SessionService


router = APIRouter(
    prefix="/auth/session",
    tags=["sessions"],
    responses={404: {"description": "Not found"}},
)


@router.get(
    "",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def api_session_status(session: Session = Depends(get_session)):
    return SessionService(session).status()


@router.post(
    "/refresh",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def api_session_refresh(session: Session = Depends(get_session)):
    return SessionService(session).refresh()
