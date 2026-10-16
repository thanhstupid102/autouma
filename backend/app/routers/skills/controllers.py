from fastapi import APIRouter, Depends

from backend.app.schemas.envelope import ApiResponse
from backend.app.context import get_ctx, AppContext


router = APIRouter(
    prefix="/skills",
    tags=["skills"],
    responses={404: {"description": "Not found"}},
)


@router.get(
    "",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def api_get_skills(ctx: AppContext = Depends(get_ctx)):
    # Serialize as an ARRAY (each entry carries its own "id"), matching every other
    # collection endpoint. ctx.skill_data is keyed by skill-id string internally.
    return {"success": True, "skills": [{"id": k, **v} for k, v in ctx.skill_data.items()]}
