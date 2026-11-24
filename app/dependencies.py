import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request


def get_db(request: Request):
    with request.app.state.sessions() as db:
        yield db


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def cookie_digest(settings, token):
    return hmac.new(settings.token.encode(), token.encode(), hashlib.sha256).hexdigest()


def session_digest(request):
    token = request.cookies.get(request.app.state.settings.cookie_name, "")
    return cookie_digest(request.app.state.settings, token) if len(token) == 43 else ""


def csrf_token(request):
    settings = request.app.state.settings
    if settings.disable_auth:
        return request.app.state.local_csrf
    return digest("csrf:" + request.cookies.get(settings.cookie_name, ""))


def check_origin(request):
    if request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
        raise HTTPException(403, "Запрос с другого сайта")
    origin = request.headers.get("origin")
    if origin:
        settings = request.app.state.settings
        scheme = "https" if settings.production else request.url.scheme
        expected = settings.origin or f"{scheme}://{request.url.netloc}"
        if origin != expected:
            raise HTTPException(403, "Запрос с другого сайта")


def require_user(request: Request):
    from app.models import AuthSession

    if not request.app.state.settings.disable_auth:
        with request.app.state.sessions() as db:
            login = db.get(AuthSession, session_digest(request))
            if login is None or login.expires <= int(time.time()):
                raise HTTPException(401, "Войдите в Watch Tracker")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
        candidate = request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(candidate.encode(), csrf_token(request).encode()):
            raise HTTPException(403, "Запрос не подтверждён. Обновите страницу.")
