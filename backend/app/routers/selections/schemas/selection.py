from pydantic import BaseModel


class UISelectionRequest(BaseModel):
    selection: dict
