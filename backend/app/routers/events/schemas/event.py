from pydantic import BaseModel


class EventPrefsRequest(BaseModel):
    prefs: dict
