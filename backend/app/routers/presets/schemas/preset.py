from pydantic import BaseModel


class SaveRacesRequest(BaseModel):
    races: list[int]


class SavePresetRequest(BaseModel):
    preset: dict
