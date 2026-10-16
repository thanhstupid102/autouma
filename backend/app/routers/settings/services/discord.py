from urllib.parse import urlsplit

from fastapi.responses import JSONResponse

from integrations.discord import notify
from core.settings import Settings


WEBHOOK_TOKEN_MASK = "••••••••"
_DISCORD_WEBHOOK_HOSTS = {
    "discord.com",
    "www.discord.com",
    "canary.discord.com",
    "ptb.discord.com",
    "discordapp.com",
    "www.discordapp.com",
    "canary.discordapp.com",
    "ptb.discordapp.com",
}


def redact_webhook_url(webhook_url: str | None) -> str | None:
    """Return a safe Discord webhook preview without exposing the token."""
    stored = str(webhook_url or "").strip()
    if not stored:
        return None

    try:
        parsed = urlsplit(stored)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return WEBHOOK_TOKEN_MASK

    if (
        parsed.scheme.lower() != "https"
        or hostname is None
        or hostname.lower() not in _DISCORD_WEBHOOK_HOSTS
        or port is not None
        or parsed.username is not None
        or parsed.password is not None
    ):
        return WEBHOOK_TOKEN_MASK

    path_parts = parsed.path.rstrip("/").split("/")
    is_unversioned = path_parts[:3] == ["", "api", "webhooks"]
    is_versioned = (
        len(path_parts) >= 4
        and path_parts[:2] == ["", "api"]
        and path_parts[2].startswith("v")
        and path_parts[2][1:].isdigit()
        and path_parts[3] == "webhooks"
    )
    expected_parts = 5 if is_unversioned else 6 if is_versioned else 0
    if len(path_parts) != expected_parts:
        return WEBHOOK_TOKEN_MASK

    webhook_id = path_parts[-2]
    token = path_parts[-1]
    if not webhook_id.isdigit() or not token:
        return WEBHOOK_TOKEN_MASK

    safe_path = "/".join(path_parts[:-1])
    return f"https://{parsed.netloc}{safe_path}/{WEBHOOK_TOKEN_MASK}"


class DiscordConfigService:
    def __init__(self, source_root, state_root):
        self.source_root = source_root
        self.state_root = state_root

    @staticmethod
    def _success(**content):
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                **content,
            },
        )

    @staticmethod
    def _error(detail: str, status_code: int = 400):
        return JSONResponse(
            status_code=status_code,
            content={
                "success": False,
                "detail": detail,
            },
        )

    def get_webhook_url(self):
        url = notify.get_webhook_url(self.state_root)
        mention = notify.get_error_mention(self.state_root)
        return self._success(
            configured=bool(url),
            webhook_preview=redact_webhook_url(url),
            error_mention=(
                notify.format_error_mention(mention) if mention is not None else None
            ),
        )

    def set_webhook_url(
        self,
        webhook_url: str | None = None,
        error_mention: str | None = None,
        update_error_mention: bool = False,
    ):
        mention = None
        if update_error_mention and error_mention is not None:
            try:
                mention = notify.normalize_error_mention(error_mention)
            except ValueError as exc:
                return self._error(str(exc))

        if webhook_url is not None:
            notify.set_webhook_url(self.state_root, webhook_url)
        if update_error_mention:
            if mention is None:
                notify.clear_error_mention(self.state_root)
            else:
                notify.set_error_mention(self.state_root, mention)

        url = notify.get_webhook_url(self.state_root)
        stored_mention = notify.get_error_mention(self.state_root)
        return self._success(
            configured=bool(url),
            error_mention=(
                notify.format_error_mention(mention)
                if update_error_mention and mention is not None
                else (
                    notify.format_error_mention(stored_mention)
                    if stored_mention is not None
                    else None
                )
            ),
        )

    def test_webhook(self):
        if not notify.get_webhook_url(self.state_root):
            return self._error("No webhook URL configured")
        sumary = {
            "status": "finished",
            "account": Settings.SWEEP_ACCOUNT,
            "uma_name": "Webhook Test",
            "preset": "test",
            "final_turn": 78,
            "duration": "0.0 mnt",
            "stats": {"speed": 1200, "stamina": 800, "power": 1000, "guts": 600, "wit": 900, "skill_point": 350, "fans": 123456},
            "skills_bought": 0,
            "races": 0,
            "fans": 123456,
            "factor_ids": [201, 3302, 1000702, 1001201, 1001902, 2002001, 2015302, 10060201],
            "loop_index": 2,
            "loop_target": 5,
        }
        result = notify.send_career_summary(
            self.source_root,
            self.state_root,
            sumary,
        )
        return self._success(success=result)
