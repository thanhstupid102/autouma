from fastapi import APIRouter, Depends, Response

from backend.app.schemas.envelope import ApiResponse
from backend.app.context import get_ctx, AppContext

from .schemas.account import ExportAccountsRequest, ImportAccountsRequest
from .services.account_service import AccountService


router = APIRouter(
    prefix="/accounts",
    tags=["accounts"],
    responses={404: {"description": "Not found"}},
)


@router.get(
    "",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def list_accounts(ctx: AppContext = Depends(get_ctx)):
    return AccountService(ctx).list_all()


@router.delete(
    "/{name}",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def delete_account(name: str, ctx: AppContext = Depends(get_ctx)):
    return AccountService(ctx).delete(name)


@router.post("/export")
async def export_accounts(req: ExportAccountsRequest, ctx: AppContext = Depends(get_ctx)):
    blob = AccountService(ctx).export(req.names, req.passphrase)
    return Response(content=blob, media_type="application/octet-stream",
                    headers={"Content-Disposition": 'attachment; filename="accounts.umaacct"'})


@router.post(
    "/import",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
async def import_accounts(req: ImportAccountsRequest, ctx: AppContext = Depends(get_ctx)):
    return AccountService(ctx).import_bundle(req.bundle_b64, req.passphrase, req.overwrite)
