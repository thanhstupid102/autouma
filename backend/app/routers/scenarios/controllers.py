from fastapi import APIRouter

from backend.app.schemas.envelope import ApiResponse
from career_bot.scenarios import runnable_scenarios


router = APIRouter(
    prefix="/scenarios",
    tags=["scenarios"],
    responses={404: {"description": "Not found"}},
)


@router.get(
    "",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def api_get_scenarios():
    return {"success": True, "scenarios": runnable_scenarios()}
