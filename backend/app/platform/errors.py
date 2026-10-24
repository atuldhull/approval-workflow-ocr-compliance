"""Platform-only errors. They extend the shared ContractError so the existing handler maps them."""
from contracts.errors import ContractError


class ServiceUnavailable(ContractError):
    """A dependency the request needs (identity or policy service) cannot be reached. Never fall back to allow."""
    status_code = 503


class PreconditionRequired(ContractError):
    status_code = 428
