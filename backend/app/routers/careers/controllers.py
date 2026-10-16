from fastapi import APIRouter, Depends, Query

from backend.app.schemas.envelope import ApiResponse
from backend.app.deps import get_session
from uma_api.session import Session

from .schemas.career import (
    StartCareerRequest,
    RunCareerRequest,
    CareerActionRequest,
    DeleteCareerRequest,
    BurnClocksRequest,
)
from .services.career_service import CareerService


router = APIRouter(
    prefix="/career",
    tags=["careers"],
    responses={404: {"description": "Not found"}},
)


@router.post(
    "/start",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def start_career(req: StartCareerRequest, session: Session = Depends(get_session)):
    return await CareerService(session).start(req)


@router.post(
    "/run",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def run_career(req: RunCareerRequest, session: Session = Depends(get_session)):
    return await CareerService(session).run(req)


@router.get(
    "/runner",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def career_runner_status(session: Session = Depends(get_session)):
    return CareerService(session).runner_status()


@router.get(
    "/event-info",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def get_event_info(session: Session = Depends(get_session)):
    return CareerService(session).event_info()


@router.post(
    "/runner/stop",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def stop_career_runner(session: Session = Depends(get_session)):
    return CareerService(session).stop_runner()


@router.post(
    "/runner/pause",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def pause_career_runner(session: Session = Depends(get_session)):
    return CareerService(session).pause_runner()


@router.post(
    "/runner/resume",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def resume_career_runner(session: Session = Depends(get_session)):
    return CareerService(session).resume()


@router.patch(
    "/runner",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def set_burn_clocks(req: BurnClocksRequest, session: Session = Depends(get_session)):
    return CareerService(session).set_burn_clocks(req.burn_clocks)


@router.get(
    "/friends",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def get_friend_list(
    exclude_viewer_ids: list[int] = Query(default=[]),
    session: Session = Depends(get_session),
):
    return CareerService(session).friends(exclude_viewer_ids)


@router.post(
    "/action",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def career_action(req: CareerActionRequest, session: Session = Depends(get_session)):
    return CareerService(session).action(
        req.command_type,
        req.command_id,
        req.current_turn,
        req.current_vital,
        req.command_group_id,
        req.select_id,
    )


@router.post(
    "/delete",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def delete_career(req: DeleteCareerRequest, session: Session = Depends(get_session)):
    return CareerService(session).delete_career(req.current_turn)
