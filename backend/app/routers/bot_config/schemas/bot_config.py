from typing import Any

from pydantic import BaseModel


class SaveBotConfigRequest(BaseModel):
    config: dict[str, Any]
