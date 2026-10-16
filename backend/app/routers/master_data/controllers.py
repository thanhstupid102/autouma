from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from backend.app.constants.doc_tags import Module, TagBuilder
from backend.app.context import get_ctx, AppContext
import uma_data

from .schemas.master_data import MasterDataPathRequest, MasterDataStatusResponse

router = APIRouter(
    prefix="/master-data",
    tags=[TagBuilder.name(Module.MASTER_DATA)],
    responses={404: {"description": "Not found"}},
)


# --------------------------
# Status
# --------------------------

@router.get(
    "/status",
    response_model=MasterDataStatusResponse,
    response_model_exclude_unset=True,
)
def master_data_status(ctx: AppContext = Depends(get_ctx)):
    return uma_data.status(ctx.base_dir, ctx.state_root)


# --------------------------
# Path
# --------------------------

@router.post("/config")
def set_master_data_path(
    payload: MasterDataPathRequest,
    ctx: AppContext = Depends(get_ctx),
):
    uma_data.set_master_mdb_path(
        ctx.base_dir, payload.master_mdb_path, ctx.state_root,
    )
    response = uma_data.status(ctx.base_dir, ctx.state_root)
    status_code = 200 if response["exists"] else 400
    if response["exists"]:
        result = uma_data.generate(ctx.base_dir, state_root=ctx.state_root)
        if result.get("success"):
            response["generated"] = result.get("legacy", [])
            status_code = 200
        else:
            response["generation_error"] = result.get("detail") or "master_data generation failed"
            status_code = 400
    return JSONResponse(status_code=status_code, content=response)


# --------------------------
# Generate
# --------------------------

@router.post("/generate")
def generate_master_data(ctx: AppContext = Depends(get_ctx)):
    result = uma_data.generate(ctx.base_dir, state_root=ctx.state_root)
    if not result.get("success"):
        return JSONResponse(status_code=400, content=result)
    return JSONResponse(status_code=200, content=result)
