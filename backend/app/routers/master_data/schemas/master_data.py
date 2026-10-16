from pydantic import BaseModel, ConfigDict


class MasterDataPathRequest(BaseModel):
    master_mdb_path: str


class MasterDataStatusResponse(BaseModel):
    """uma_data.status() passthrough (§12.6 response contract).

    Deliberately NOT the ApiResponse {success, detail} envelope — the frontend
    reads the raw status dict. extra="allow" + exclude_unset re-emits exactly
    the keys the service set; only `exists` is contractual. /config and
    /generate return this same status shape (plus generated/generation_error)
    via JSONResponse with a data-dependent status code, so their models are
    documentation-only.
    """

    model_config = ConfigDict(extra="allow")

    exists: bool
