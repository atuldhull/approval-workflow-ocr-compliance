"""Builds the single FastAPI application.

Modules are discovered automatically: any package under app/ may provide models.py (tables),
wiring.py (a wire() function that registers its ports) and api.py (a `router`). Adding a module
therefore never requires editing this file.
"""
import importlib
import pkgutil
from types import ModuleType

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import app as app_pkg
from app.platform.http_security import security_headers
from contracts.errors import ContractError

FIRST = "platform"  # wired first: everyone else depends on its ports


def module_names() -> list[str]:
    names = [m.name for m in pkgutil.iter_modules(app_pkg.__path__) if m.ispkg]
    return sorted(names, key=lambda n: (n != FIRST, n))


def _optional(module: str, part: str) -> ModuleType | None:
    name = f"app.{module}.{part}"
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name == name:
            return None
        raise


def load_models() -> None:
    for m in module_names():
        _optional(m, "models")


def create_app() -> FastAPI:
    load_models()
    for m in module_names():
        wiring = _optional(m, "wiring")
        if wiring is not None:
            wiring.wire()

    api = FastAPI(title="Approval Workflow, OCR & Compliance", version="0.1.0")
    api.middleware("http")(security_headers)
    for m in module_names():
        mod = _optional(m, "api")
        if mod is not None:
            api.include_router(mod.router, prefix="/api")

    @api.exception_handler(ContractError)
    async def _contract_error(request: Request, exc: ContractError):
        return JSONResponse(status_code=exc.status_code, content={"error": type(exc).__name__, "detail": str(exc)})

    return api


app = create_app()
