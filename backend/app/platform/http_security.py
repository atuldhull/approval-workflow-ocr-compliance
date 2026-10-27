"""Response headers that limit what a browser may do with API responses.

API responses are JSON only, so they get the strictest policy: never framed, never sniffed as another type,
never cached (they carry personal and case data), and a CSP that forbids any content from loading. The UI's own
CSP belongs to whatever serves the built frontend (see docs/SECURITY.md); it is not set here.
"""
from fastapi import Request

from app.platform.settings import settings

API_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


async def security_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        for name, value in API_HEADERS.items():
            response.headers.setdefault(name, value)
        if settings.app_env == "production":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response
