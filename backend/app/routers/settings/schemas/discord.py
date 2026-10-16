from pydantic import BaseModel


class DiscordWebhookRequest(BaseModel):
    webhook_url: str | None = None
    error_mention: str | None = None
