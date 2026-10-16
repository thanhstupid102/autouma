from pydantic import BaseModel


class DeleteParentsRequest(BaseModel):
    instance_ids: list[int | str]
    # When True, locked (memo) veterans in the set are unlocked before removal.
    unlock_locked: bool = False


class AutoDeleteConfigRequest(BaseModel):
    enabled: bool = False
    min_blue: int = 0
    min_pink: int = 0
    min_white: int = 0
    min_green: int = 0
    conditions: list[dict] = []
