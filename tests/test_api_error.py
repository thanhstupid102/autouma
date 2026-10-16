"""ApiError typed-exception contract.

Locks in that ApiError carries structured result_code/endpoint while keeping
str() byte-identical to the historical `f'API error {rc} on {ep}: {detail}'`
form, so the many existing str()-matching call sites keep working, and that
`api_error_result_code` reads the attribute rather than regex-parsing.
"""
import os

os.environ.setdefault("SWEEPY_SKIP_STARTUP_GEN", "1")

from uma_api import errors
from uma_api.errors import ApiError


def test_apierror_is_exception():
    assert isinstance(ApiError(205, "single_mode/x"), Exception)


def test_apierror_default_message_is_historical_format():
    # Must match the old  f'API error {rc} on {ep}: {err_detail}'  byte for byte.
    err = ApiError(205, "single_mode/index", "some detail")
    assert str(err) == "API error 205 on single_mode/index: some detail"


def test_apierror_carries_structured_fields():
    err = ApiError(102, "single_mode_free/load", "desync")
    assert err.result_code == 102
    assert err.endpoint == "single_mode_free/load"
    assert err.detail == "desync"


def test_apierror_explicit_message_override_preserved():
    # The 208 special case passes an explicit message that is not the default
    # "... : {detail}" shape; str() must be exactly that message.
    msg = "API error 208 (server busy, sid resync needed) on single_mode_free/multi_item_use"
    err = ApiError(208, "single_mode_free/multi_item_use", message=msg)
    assert str(err) == msg
    assert err.result_code == 208


def test_api_error_result_code_prefers_attribute():
    # Attribute path: exact result_code even when the message would be
    # regex-parsed to the same value -- and identical to the legacy behaviour.
    assert errors.api_error_result_code(ApiError(205, "ep", "d")) == 205
    assert errors.api_error_result_code(ApiError(208, "ep", message="API error 208 (busy) on ep")) == 208


def test_api_error_result_code_matches_string_fallback():
    # A raise site that becomes ApiError(rc, ...) yields the SAME code the old
    # regex would have parsed from the identical string -- no behavior drift.
    ep = "single_mode/index"
    for rc in (102, 205, 214, 208):
        err = ApiError(rc, ep, "x")
        assert errors.api_error_result_code(err) == rc
        assert errors.api_error_result_code(Exception(str(err))) == rc
