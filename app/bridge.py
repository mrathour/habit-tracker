"""The response envelope every JS API method returns.

Methods exposed to the UI are wrapped with :func:`bridge_method`. A call never rejects in
JavaScript: it resolves to ``{"ok": true, "data": ...}`` or ``{"ok": false, "error": {...}}``,
where the error is an :class:`~app.errors.ErrorReport` that is already logged and redacted.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Concatenate, TypedDict, cast

from app.errors import report_exception


class OkResponse[T](TypedDict):
    ok: bool
    data: T


class ErrorResponse(TypedDict):
    ok: bool
    error: dict[str, str | None]


type BridgeResponse[T] = OkResponse[T] | ErrorResponse


def bridge_method[S, **P, T](
    method: Callable[Concatenate[S, P], T],
) -> Callable[Concatenate[S, P], BridgeResponse[T]]:
    @functools.wraps(method)
    def wrapper(self: S, *args: P.args, **kwargs: P.kwargs) -> BridgeResponse[T]:
        try:
            return {"ok": True, "data": method(self, *args, **kwargs)}
        except Exception as exc:  # noqa: BLE001 - every failure becomes an error response
            report = report_exception(exc, context=f"bridge call {method.__name__}()")
            return {"ok": False, "error": report.to_dict()}

    return cast(Callable[Concatenate[S, P], BridgeResponse[T]], wrapper)
