"""One place where a typed domain exception becomes an HTTP response.

§12.6 "Typed exceptions" asks for the translation to happen ONCE at the
controller boundary instead of being repeated at every call site. Before this
module, ``BotConfigValidationError`` was caught and re-raised as the *same*
``HTTPException(400, str(exc))`` in three consecutive controllers.

Byte-identity is by CONSTRUCTION rather than imitation: the handler builds
exactly the ``HTTPException`` the controller used to build and hands it to
FastAPI's own :func:`fastapi.exception_handlers.http_exception_handler` -- the
very function that rendered it before. Status code, ``{"detail": ...}`` body and
headers therefore cannot drift apart.

Scope is deliberately narrow. Only the exception types registered below are
translated; anything else still propagates untouched, so a genuine bug keeps
surfacing as a 500 instead of being laundered into a tidy 4xx. Adding a type
here is a real API-contract change -- it converts that exception's 500 into the
mapped status for *every* route -- so each entry needs its own reachability
argument, not just a wish for tidier controllers.
"""

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from career_bot.bot_config import BotConfigValidationError
from uma_api.account_link import LinkInputValidationError


async def bot_config_validation_error_handler(
    request: Request, exc: Exception,
) -> Response:
    """400 + the validator's own message: what the bot-config routes always did.

    Reachability: ``BotConfigValidationError`` escapes to a route only from the
    three ``/api/bot-config*`` handlers (via ``BotConfigStore.read_active`` /
    ``write_active``). Every other path that can raise it -- the career
    launch/loop code calling ``apply_runtime_bot_config`` -- already sits inside
    its own ``except Exception``, so this handler never sees it there.
    """
    return await http_exception_handler(
        request, HTTPException(status_code=400, detail=str(exc)),
    )


async def request_validation_error_handler(
    request: Request, exc: Exception,
) -> Response:
    """Hide transition-link secrets while preserving every other 422 response."""
    if request.url.path.endswith("/api/auth/transition-code/chain"):
        return JSONResponse(
            status_code=422,
            content={"detail": "Invalid Trainer ID or link password"},
        )
    assert isinstance(exc, RequestValidationError)
    return await request_validation_exception_handler(request, exc)


async def link_input_validation_error_handler(
    request: Request, exc: Exception,
) -> Response:
    """Map local account-link validation to a secret-free client error."""
    assert isinstance(exc, LinkInputValidationError)
    return await http_exception_handler(
        request,
        HTTPException(
            status_code=400,
            detail="Invalid Trainer ID or link password",
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Install the domain-exception → HTTP-envelope mappings on ``app``."""
    app.add_exception_handler(
        BotConfigValidationError, bot_config_validation_error_handler,
    )
    app.add_exception_handler(
        RequestValidationError, request_validation_error_handler,
    )
    app.add_exception_handler(
        LinkInputValidationError, link_input_validation_error_handler,
    )
