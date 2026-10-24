"""Errors any module may raise; the API layer maps them to HTTP status codes."""


class ContractError(Exception):
    status_code = 400


class ValidationFailed(ContractError):
    status_code = 422


class NotFound(ContractError):
    status_code = 404


class Forbidden(ContractError):
    status_code = 403


class Conflict(ContractError):
    status_code = 409
