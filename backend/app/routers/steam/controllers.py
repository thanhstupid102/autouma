from fastapi import APIRouter, Depends

from backend.app.deps import get_session
from uma_api.session import Session

from .schemas.steam import QrPollResponse, QrStartResponse
from .services.steam_service import SteamService


router = APIRouter(
    prefix="/auth/steam",
    tags=["steams"],
    responses={404: {"description": "Not found"}},
)


@router.post(
    "/qr/start",
    response_model=QrStartResponse,
    response_model_exclude_unset=True,
)
async def api_steam_qr_start(session: Session = Depends(get_session)):
    return await SteamService(session).qr_start()


@router.get(
    "/qr/poll",
    response_model=QrPollResponse,
    response_model_exclude_unset=True,
)
async def api_steam_qr_poll(session: Session = Depends(get_session)):
    return SteamService(session).qr_poll()
