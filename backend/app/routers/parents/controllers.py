from fastapi import APIRouter, Depends

from backend.app.schemas.envelope import ApiResponse
from backend.app.deps import get_session
from uma_api.session import Session

from .schemas.parent import DeleteParentsRequest, AutoDeleteConfigRequest
from .services.parent_service import ParentService


router = APIRouter(
    prefix="/parents",
    tags=["parents"],
    responses={404: {"description": "Not found"}},
)


@router.post(
    "/refresh",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def api_refresh_parents(session: Session = Depends(get_session)):
    return ParentService(session).refresh()


# Bulk delete by trained-character instance id. Uses the DELETE verb (not the old
# POST /delete) per the API-naming convention; the id list + unlock flag stay in a
# JSON body (a legitimate REST pattern for a mixed-type bulk delete) rather than
# query params, so ParentService's id handling is untouched.
@router.delete(
    "",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def api_delete_parents(
    payload: DeleteParentsRequest,
    session: Session = Depends(get_session),
):
    return ParentService(session).delete(payload.instance_ids, payload.unlock_locked)


@router.get(
    "/auto-delete-config",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def api_get_auto_delete_config(session: Session = Depends(get_session)):
    return ParentService(session).get_auto_delete_config()


@router.post(
    "/auto-delete-config",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def api_set_auto_delete_config(
    payload: AutoDeleteConfigRequest,
    session: Session = Depends(get_session),
):
    return ParentService(session).set_auto_delete_config(payload.model_dump())
