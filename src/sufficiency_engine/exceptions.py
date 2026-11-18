"""Structured exceptions for configuration, state, and integration failures."""


class SufficiencyError(Exception):
    """Base exception with a stable machine-readable code."""

    code = "sufficiency_error"
    retryable = False


class ConfigurationError(SufficiencyError):
    """The engine or its input is not configured correctly."""

    code = "configuration_error"


class ModelInvocationError(SufficiencyError):
    """The model callback failed."""

    code = "model_invocation_error"


class TransientModelError(ModelInvocationError):
    """A model failure that the callback explicitly marks as retryable."""

    code = "transient_model_error"
    retryable = True


class ModelResponseError(SufficiencyError):
    """A model response failed normalization or schema validation."""

    code = "model_response_error"


class CallbackError(SufficiencyError):
    """An application callback failed."""

    code = "callback_error"


class ClarificationError(SufficiencyError):
    """An interaction or answer could not be processed."""

    code = "clarification_error"


class PersistenceError(SufficiencyError):
    """Session persistence failed."""

    code = "persistence_error"


class SessionConflictError(PersistenceError):
    """A concurrent session mutation or revision conflict occurred."""

    code = "session_conflict"


class SerializationError(PersistenceError):
    """A persisted state is invalid or has an unsupported version."""

    code = "serialization_error"


class ProvenanceError(SufficiencyError):
    """A required audit operation failed."""

    code = "provenance_error"
    retryable = True


class DependencyError(SufficiencyError):
    """A requirement graph has invalid references or cycles."""

    code = "invalid_dependencies"
