"""Configuration and explicit resource bounds."""

from pydantic import BaseModel, ConfigDict, Field


class Limits(BaseModel):
    """Bounds applied to untrusted input and callback execution.

    Byte limits use UTF-8 encoded JSON or task text. Callback timeouts do not
    forcibly stop an already running synchronous callback.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_input_bytes: int = Field(default=65_536, ge=1)
    max_requirements: int = Field(default=256, ge=1)
    max_dependency_edges: int = Field(default=2_048, ge=0)
    max_questions: int = Field(default=64, ge=1)
    max_answer_bytes: int = Field(default=16_384, ge=1)
    callback_timeout_seconds: float = Field(default=120.0, gt=0, allow_inf_nan=False)


class EngineConfig(BaseModel):
    """Policy, retry, and resource settings for one engine instance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_iterations: int = Field(default=5, ge=0, le=100)
    max_model_retries: int = Field(default=2, ge=0, le=10)
    require_optional: bool = False
    allow_assumptions: bool = False
    limits: Limits = Field(default_factory=Limits)
