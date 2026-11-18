"""Pydantic response schemas for the HTTP API shell."""

from typing import Literal
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok"] = Field(description="HTTP process is alive.")


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"] = Field(
        description="Whether dependencies can currently serve API work."
    )
    postgres: bool = Field(description="PostgreSQL readiness check succeeded.")
    nats: bool = Field(description="NATS readiness check succeeded.")


class AuthCheckResponse(BaseModel):
    authenticated: bool = Field(
        description="The supplied token matches the local shared secret."
    )


class ErrorResponse(BaseModel):
    error: str = Field(description="Stable error category.")
    detail: str = Field(description="Safe explanation without private values.")
