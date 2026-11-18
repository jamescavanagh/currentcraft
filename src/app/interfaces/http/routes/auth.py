"""Protected authentication verification route."""

from fastapi import APIRouter, Depends

from ..schemas import AuthCheckResponse
from ..security import require_token

router = APIRouter(tags=["authentication"])


@router.get(
    "/auth/check",
    response_model=AuthCheckResponse,
    dependencies=[Depends(require_token)],
)
def auth_check() -> AuthCheckResponse:
    return AuthCheckResponse(authenticated=True)
