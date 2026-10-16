from fastapi import APIRouter, Depends

from backend.app.constants.doc_tags import Module, TagBuilder
from backend.app.schemas.envelope import ApiResponse
from backend.app.context import get_ctx, AppContext
from backend.app.deps import get_session
from uma_api.session import Session

from .schemas.delay import ApiDelayRequest
from .schemas.discord import DiscordWebhookRequest
from .services.delay import DelayConfigService
from .services.discord import DiscordConfigService


router = APIRouter(
    prefix="/settings",
    tags=[TagBuilder.name(Module.SETTINGS)],
    responses={404: {"description": "Not found"}},
)


# --------------------------
# Turn delay
# --------------------------

@router.get(
    "/turn-delay",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def api_get_turn_delay(
    session: Session = Depends(get_session)
):
    return DelayConfigService().get_turn_delay(session=session)


@router.post(
    "/turn-delay",
    response_model=ApiResponse,
    response_model_exclude_unset=True,
)
def api_set_turn_delay(
    payload: ApiDelayRequest,
    session: Session = Depends(get_session)
):
    return DelayConfigService().set_turn_delay(
        session=session,
        min_value=payload.min,
        max_value=payload.max,
        disabled=payload.disabled,
    )


# --------------------------
# Discord webhook
# --------------------------

@router.get("/discord-webhook")
def api_get_discord_webhook(ctx: AppContext = Depends(get_ctx)):
    return DiscordConfigService(ctx.base_dir, ctx.state_root).get_webhook_url()


@router.post("/discord-webhook")
def api_set_discord_webhook(
    payload: DiscordWebhookRequest,
    ctx: AppContext = Depends(get_ctx),
):
    fields = payload.model_fields_set
    return DiscordConfigService(ctx.base_dir, ctx.state_root).set_webhook_url(
        webhook_url=payload.webhook_url if "webhook_url" in fields else None,
        error_mention=payload.error_mention,
        update_error_mention="error_mention" in fields,
    )


@router.post("/discord-webhook/test")
def api_test_discord_webhook(ctx: AppContext = Depends(get_ctx)):
    return DiscordConfigService(ctx.base_dir, ctx.state_root).test_webhook()
