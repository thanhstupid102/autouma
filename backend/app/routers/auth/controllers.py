from fastapi import APIRouter, Depends

from backend.app.schemas.envelope import ApiResponse
from backend.app.deps import get_session
from uma_api.session import Session

from .schemas.auth import (
    LoginRequest,
    SteamUnbindPreflightRequest,
    SteamUnbindRequest,
    TransitionCodeChainRequest,
)
from .services.auth_service import AuthService


router = APIRouter(
    prefix="",
    tags=["auth"],
    responses={404: {"description": "Not found"}},
)


@router.post(
    "/auth/login",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def api_login(payload: LoginRequest, session: Session = Depends(get_session)):
    return await AuthService(session).login(payload)


@router.post(
    "/auth/transition-code/chain",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def api_chain_transition_code(
    payload: TransitionCodeChainRequest,
    session: Session = Depends(get_session),
):
    return await AuthService(session).chain_transition_code(payload)


@router.post(
    "/auth/leave-session",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def api_leave_session(session: Session = Depends(get_session)):
    return AuthService(session).leave_session()


@router.post(
    "/auth/steam/unbind/preflight",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def api_preflight_steam_unbind(
    payload: SteamUnbindPreflightRequest,
    session: Session = Depends(get_session),
):
    """Diagnostic only: verify Trainer-ID recovery without removing a link."""
    return AuthService(session).preflight_steam_unbind(payload)


# This route maps directly to account/steam_chain_disconnect; the UI calls it
# "Remove Uma link" to describe the action from the local account's side.
@router.post(
    "/auth/steam/unbind",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def api_steam_unbind(
    payload: SteamUnbindRequest,
    session: Session = Depends(get_session),
):
    return AuthService(session).steam_unbind(payload)
