from pydantic import BaseModel


class ExportAccountsRequest(BaseModel):
    names: list[str]
    passphrase: str


class ImportAccountsRequest(BaseModel):
    bundle_b64: str
    passphrase: str
    overwrite: bool = False
