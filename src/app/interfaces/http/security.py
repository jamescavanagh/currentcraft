"""Shared bearer token verification dependency."""

import hmac

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)


def require_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    expected = request.app.state.container.settings.api_token

    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Authentication is not configured",
        )

    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not hmac.compare_digest(
            credentials.credentials.encode("utf-8"),
            expected.encode("utf-8"),
        )
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication",
            headers={"WWW-Authenticate": "Bearer"},
        )
