from fastapi import APIRouter, Depends

from backend.app.constants.doc_tags import Module, TagBuilder
from backend.app.schemas.envelope import ApiResponse
from backend.app.context import get_ctx, AppContext

from .schemas.bot_config import SaveBotConfigRequest


router = APIRouter(
    prefix="/bot-config",
    tags=[TagBuilder.name(Module.BOT_CONFIG)],
    responses={404: {"description": "Not found"}},
)

# A `BotConfigValidationError` raised by any handler below is translated to
# `HTTPException(400, str(exc))` by the app-level handler registered in
# backend/app/exception_handlers.py -- the identical three lines this module
# used to repeat per route (§12.6 typed exceptions).


@router.get(
    "",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def get_bot_config(ctx: AppContext = Depends(get_ctx)):
    return ctx.bot_config_store.response()


@router.post(
    "",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def save_bot_config(
    payload: SaveBotConfigRequest,
    ctx: AppContext = Depends(get_ctx),
):
    store = ctx.bot_config_store
    config = store.write_active(payload.config)
    response = store.response()
    response["config"] = config
    return response


@router.post(
    "/reset",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def reset_bot_config(ctx: AppContext = Depends(get_ctx)):
    store = ctx.bot_config_store
    config = store.reset_active()
    response = store.response()
    response["config"] = config
    return response
