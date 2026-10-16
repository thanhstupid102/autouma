from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""
    code: str = ""
    steam_id: str = ""
    steam_session_ticket: str = ""


class TransitionCodeChainRequest(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    input_viewer_id: str = Field(
        min_length=9,
        max_length=12,
        pattern=r"^[0-9]+$",
    )
    password: str = Field(
        min_length=8,
        max_length=16,
        pattern=r"^[0-9A-Za-z]+$",
    )
    verify_only: bool = False

    @field_validator("password")
    @classmethod
    def validate_password_classes(cls, password: str) -> str:
        if not (
            any(char.isascii() and char.isdigit() for char in password)
            and any("a" <= char <= "z" for char in password)
            and any("A" <= char <= "Z" for char in password)
        ):
            raise ValueError("link password must include a digit and both letter cases")
        return password


class SteamUnbindRequest(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    confirm_account_name: str
    link_password: str | None = Field(
        default=None,
        min_length=8,
        max_length=16,
        pattern=r"^[0-9A-Za-z]+$",
    )

    @field_validator("link_password")
    @classmethod
    def validate_password_classes(cls, password: str | None) -> str | None:
        if password is None:
            return password
        if not (
            any(char.isascii() and char.isdigit() for char in password)
            and any("a" <= char <= "z" for char in password)
            and any("A" <= char <= "Z" for char in password)
        ):
            raise ValueError("link password must include a digit and both letter cases")
        return password


class SteamUnbindPreflightRequest(SteamUnbindRequest):
    """Diagnostic recovery check; its link password is always required."""

    link_password: str = Field(
        min_length=8,
        max_length=16,
        pattern=r"^[0-9A-Za-z]+$",
    )
