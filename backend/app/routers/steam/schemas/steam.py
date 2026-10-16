"""Steam QR transport contract (§12.6 response-contract finish).

These routes deliberately do NOT use the ApiResponse {success, detail}
envelope: the frontend (frontend/src/api/auth.ts QrStartData/QrPollData)
consumes the raw QrLoginSession snapshot shape. The models document and
validate that contract without changing a byte of the payload
(extra="allow" + response_model_exclude_unset passes the handler's dict
through re-emitting exactly the keys it set).
"""

from pydantic import BaseModel, ConfigDict


class QrStartResponse(BaseModel):
    """POST /auth/steam/qr/start — challenge handoff."""

    model_config = ConfigDict(extra="allow")

    status: str
    challenge_url: str = ""


class QrPollResponse(BaseModel):
    """GET /auth/steam/qr/poll — raw QrLoginSession.snapshot() passthrough.

    "idle" when no session was started; otherwise the snapshot carries
    status/challenge_url/error/steam_id as the login script progresses.
    """

    model_config = ConfigDict(extra="allow")

    status: str
