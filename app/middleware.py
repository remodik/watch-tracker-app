from fastapi import HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse

from app.dependencies import require_user

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' https:; "
    "font-src 'self'; connect-src 'self'; worker-src 'self'; manifest-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


class SecurityMiddleware:
    def __init__(self, app, production):
        self.app = app
        self.production = production

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]

        async def with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.update(
                    {
                        "Content-Security-Policy": CSP,
                        "X-Content-Type-Options": "nosniff",
                        "X-Frame-Options": "DENY",
                        "Referrer-Policy": "no-referrer",
                        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                        "Cross-Origin-Opener-Policy": "same-origin",
                    }
                )
                if self.production:
                    headers["Strict-Transport-Security"] = "max-age=31536000"
                if path.startswith("/api/"):
                    headers["Cache-Control"] = "no-store"
            await send(message)

        if scope["method"] in {"POST", "PUT", "PATCH", "DELETE"}:
            if path.startswith("/api/") and path.rstrip("/") != "/api/auth/login":
                try:
                    await run_in_threadpool(require_user, Request(scope))
                except HTTPException as error:
                    await JSONResponse({"detail": error.detail}, status_code=error.status_code)(
                        scope, receive, with_headers
                    )
                    return
                except SQLAlchemyError:
                    await JSONResponse({"detail": "Ошибка базы данных"}, status_code=503)(
                        scope, receive, with_headers
                    )
                    return
            limit = (
                16 * 1024 * 1024
                if path in {"/api/items/bulk-import", "/api/items/bulk-import/preview"}
                else 128 * 1024
            )
            if path.rstrip("/") == "/api/auth/login":
                limit = 4096
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > limit:
                    await JSONResponse({"detail": "Слишком большой запрос"}, status_code=413)(
                        scope,
                        receive,
                        with_headers,
                    )
                    return
                body.extend(chunk)
                if not message.get("more_body"):
                    break
            original_receive = receive

            async def replay():
                nonlocal body
                if body is None:
                    return await original_receive()
                payload, body = bytes(body), None
                return {"type": "http.request", "body": payload, "more_body": False}

            receive = replay
        await self.app(scope, receive, with_headers)
