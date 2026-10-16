import base64

import pytest

from uma_api.account_link import (
    ACCOUNT_LINK_ERROR_TYPES,
    AccountChainMaintenanceError,
    AccountLinkError,
    AccountLinkInvalidParameterError,
    AccountSignupMaintenanceError,
    AccountUdidConflictError,
    AccountUserNotFoundError,
    DataLinkMaintenanceError,
    NoChainedUserIdError,
    NoPlatformUserIdError,
    PcAccountLimitError,
    LinkInputValidationError,
    SteamAccountRemoveChainedError,
    TransitionCompletedError,
    TransitionOldAccessError,
    TransitionPasswordInvalidError,
    TransitionUserIdInvalidError,
    TransitionUserNotExistError,
    account_index,
    chain_by_transition_code,
    get_by_transition_code,
    publish_transition_code,
    steam_chain_disconnect,
    validate_link_password,
    validate_trainer_id,
)
from uma_api.errors import ApiError


VALID_PASSWORD = "NhatP0nCay0K"
VALID_PASSWORD_HASH = "48715bd20f972e70b24157f94b6a4126"
VALID_TRAINER_ID = "123456789"


class RecordingClient:
    def __init__(self, response=None, error=None):
        self.response = response or {"data_headers": {"result_code": 1}, "data": {}}
        self.error = error
        self.calls = []

    def call(self, endpoint, args=None, **kwargs):
        self.calls.append((endpoint, args, kwargs))
        if self.error is not None:
            raise self.error
        return self.response


def test_account_index_uses_verified_route_and_sdk_payload():
    client = RecordingClient()

    assert account_index(client) is client.response
    assert client.calls == [
        ("account/index", {"cygames_id_client_sdk_version": "v2"}, {}),
    ]


def test_get_requires_string_id_and_sends_string():
    client = RecordingClient()

    with pytest.raises(LinkInputValidationError):
        get_by_transition_code(
            client, password=VALID_PASSWORD, input_viewer_id=123456789,
        )
    assert client.calls == []

    get_by_transition_code(
        client, password=VALID_PASSWORD, input_viewer_id=VALID_TRAINER_ID,
    )
    assert client.calls == [
        (
            "account/get_by_transition_code",
            {
                "password": VALID_PASSWORD_HASH,
                "input_viewer_id": VALID_TRAINER_ID,
            },
            {},
        ),
    ]
    assert VALID_PASSWORD not in str(client.calls[0][1])
    assert isinstance(client.calls[0][1]["input_viewer_id"], str)


def test_publish_sends_hashed_password_without_raw_secret():
    client = RecordingClient()

    publish_transition_code(client, password=VALID_PASSWORD)

    assert client.calls == [
        (
            "account/publish_transition_code",
            {"password": VALID_PASSWORD_HASH},
            {},
        ),
    ]
    assert VALID_PASSWORD not in str(client.calls[0][1])


def test_steam_chain_disconnect_sends_an_empty_endpoint_payload():
    client = RecordingClient()

    assert steam_chain_disconnect(client) is client.response
    assert client.calls == [
        ("account/steam_chain_disconnect", {}, {}),
    ]


@pytest.mark.parametrize("invalid_id", [True, "123456789"])
def test_chain_rejects_bool_and_non_int_ids(invalid_id):
    client = RecordingClient()

    with pytest.raises(LinkInputValidationError):
        chain_by_transition_code(
            client, password=VALID_PASSWORD, input_viewer_id=invalid_id,
        )

    assert client.calls == []


def test_chain_sends_real_int_id():
    auth_key = base64.b64encode(b"\xab" * 48).decode("ascii")
    client = RecordingClient(response={
        "data_headers": {"result_code": 1},
        "data": {
            "chained_viewer_id": 123456789,
            "chained_user_name": "Trainer",
            "auth_key": auth_key,
        },
    })

    chain_by_transition_code(
        client, password=VALID_PASSWORD, input_viewer_id=123456789,
    )

    assert client.calls[0] == (
        "account/chain_by_transition_code",
        {"password": VALID_PASSWORD_HASH, "input_viewer_id": 123456789},
        {},
    )
    assert VALID_PASSWORD not in str(client.calls[0][1])
    assert type(client.calls[0][1]["input_viewer_id"]) is int


@pytest.mark.parametrize(
    "invoke",
    [
        lambda client: get_by_transition_code(
            client,
            password="Missing1Upper".lower(),
            input_viewer_id=VALID_TRAINER_ID,
        ),
        lambda client: chain_by_transition_code(
            client,
            password="Missing1Upper".lower(),
            input_viewer_id=int(VALID_TRAINER_ID),
        ),
        lambda client: publish_transition_code(
            client,
            password="Missing1Upper".lower(),
        ),
    ],
)
def test_request_helpers_reject_invalid_raw_password_before_call(invoke):
    client = RecordingClient()

    with pytest.raises(LinkInputValidationError):
        invoke(client)

    assert client.calls == []


EXPECTED_ERRORS = {
    516: TransitionOldAccessError,
    517: TransitionCompletedError,
    523: AccountLinkInvalidParameterError,
    524: AccountUserNotFoundError,
    526: TransitionUserNotExistError,
    700: TransitionPasswordInvalidError,
    701: TransitionUserIdInvalidError,
    703: AccountUdidConflictError,
    704: PcAccountLimitError,
    705: NoPlatformUserIdError,
    708: NoChainedUserIdError,
    709: SteamAccountRemoveChainedError,
    900: AccountSignupMaintenanceError,
    902: DataLinkMaintenanceError,
    903: AccountChainMaintenanceError,
}


@pytest.mark.parametrize("code, expected_type", EXPECTED_ERRORS.items())
def test_known_result_codes_map_to_exact_exception_class(code, expected_type):
    endpoint = "account/get_by_transition_code"
    client = RecordingClient(error=ApiError(code, endpoint, "rejected"))

    with pytest.raises(expected_type) as exc_info:
        get_by_transition_code(
            client, password=VALID_PASSWORD, input_viewer_id=VALID_TRAINER_ID,
        )

    assert type(exc_info.value) is expected_type
    assert exc_info.value.result_code == code
    assert ACCOUNT_LINK_ERROR_TYPES[code] is expected_type


def test_unknown_result_code_stays_ordinary_api_error():
    endpoint = "account/get_by_transition_code"
    original = ApiError(999, endpoint, "unknown")
    client = RecordingClient(error=original)

    with pytest.raises(ApiError) as exc_info:
        get_by_transition_code(
            client, password=VALID_PASSWORD, input_viewer_id=VALID_TRAINER_ID,
        )

    assert exc_info.value is original
    assert type(exc_info.value) is ApiError


def test_successful_chain_requires_all_fields_and_decodes_auth_key_to_lowercase_hex():
    raw_key = bytes(range(48))
    response = {
        "data_headers": {"result_code": 1},
        "data": {
            "chained_viewer_id": 123456789,
            "chained_user_name": "Trainer",
            "auth_key": base64.b64encode(raw_key).decode("ascii"),
        },
    }

    result = chain_by_transition_code(
        RecordingClient(response=response),
        password=VALID_PASSWORD,
        input_viewer_id=123456789,
    )

    assert result.chained_viewer_id == 123456789
    assert result.chained_user_name == "Trainer"
    assert result.auth_key_hex == raw_key.hex()
    assert result.auth_key_hex == result.auth_key_hex.lower()
    assert result.response is response


@pytest.mark.parametrize("missing", ["chained_viewer_id", "chained_user_name", "auth_key"])
def test_successful_chain_rejects_missing_response_field(missing):
    data = {
        "chained_viewer_id": 123456789,
        "chained_user_name": "Trainer",
        "auth_key": base64.b64encode(b"k" * 48).decode("ascii"),
    }
    del data[missing]

    with pytest.raises(AccountLinkError):
        chain_by_transition_code(
            RecordingClient(response={"data": data}),
            password=VALID_PASSWORD,
            input_viewer_id=123456789,
        )


@pytest.mark.parametrize("trainer_id", ["123456789", "123456789012"])
def test_trainer_id_validator_accepts_boundaries(trainer_id):
    assert validate_trainer_id(trainer_id) == trainer_id


@pytest.mark.parametrize("trainer_id", [
    "12345678",
    "1234567890123",
    "12345678a",
    "１２３４５６７８９",
    123456789,
])
def test_trainer_id_validator_rejects_invalid_values(trainer_id):
    with pytest.raises(LinkInputValidationError):
        validate_trainer_id(trainer_id)


@pytest.mark.parametrize("password", ["Abcdef1x", "AbcdefghijklmN12"])
def test_link_password_validator_accepts_boundaries(password):
    assert validate_link_password(password) == password


@pytest.mark.parametrize("password", [
    "Abcde1x",
    "AbcdefghijklmN123",
    "Abcdef1!",
    "abcdef12",
    "ABCDEF12",
    "Abcdefgh",
])
def test_link_password_validator_rejects_without_echoing_secret(password):
    with pytest.raises(LinkInputValidationError) as exc_info:
        validate_link_password(password)

    assert password not in str(exc_info.value)
    assert not isinstance(exc_info.value, AccountLinkInvalidParameterError)
    assert not hasattr(exc_info.value, "result_code")


def test_server_523_remains_server_invalid_parameter_error():
    endpoint = "account/get_by_transition_code"
    client = RecordingClient(error=ApiError(523, endpoint, "rejected"))

    with pytest.raises(AccountLinkInvalidParameterError) as exc_info:
        get_by_transition_code(
            client,
            password=VALID_PASSWORD,
            input_viewer_id=VALID_TRAINER_ID,
        )

    assert exc_info.value.result_code == 523
    assert not isinstance(exc_info.value, LinkInputValidationError)
