import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.dependencies import (
    check_origin,
    cookie_digest,
    csrf_token,
    digest,
    get_db,
    require_user,
    session_digest,
)
from app.models import AuthSession, LoginFailure, LoginLock
from app.schemas import Login

router = APIRouter(prefix="/api/auth")
SESSION_SECONDS = 30 * 24 * 3600
WINDOW_SECONDS = 600


@router.post("/login")
def login(payload: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    check_origin(request)
    if request.headers.get("x-watch-login") != "1":
        raise HTTPException(403, "Запрос не подтверждён")
    settings = request.app.state.settings
    if settings.disable_auth:
        return {"ok": True}
    now = int(time.time())
    client = digest(request.client.host if request.client else "unknown")
    if db.execute(update(LoginLock).where(LoginLock.id == 1).values(id=1)).rowcount != 1:
        raise HTTPException(503, "Блокировка входа недоступна")
    db.execute(delete(LoginFailure).where(LoginFailure.at <= now - WINDOW_SECONDS))
    valid = secrets.compare_digest(payload.token.encode(), settings.token.encode())
    if not valid:
        stats = select(func.count(), func.min(LoginFailure.at)).select_from(LoginFailure)
        total, first = db.execute(stats).one()
        attempts, first_client = db.execute(stats.where(LoginFailure.client == client)).one()
        retry = max(
            first + WINDOW_SECONDS - now if total >= 40 else 0,
            first_client + WINDOW_SECONDS - now if attempts >= 8 else 0,
        )
        if retry:
            raise HTTPException(
                429, "Слишком много попыток. Повторите позже.", headers={"Retry-After": str(retry)}
            )
        db.add(LoginFailure(client=client, at=now))
        db.commit()
        raise HTTPException(401, "Неверный ключ доступа")
    old = session_digest(request)
    db.execute(
        delete(AuthSession).where((AuthSession.expires <= now) | (AuthSession.digest == old))
    )
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(digest=cookie_digest(settings, token), expires=now + SESSION_SECONDS))
    db.commit()
    response.set_cookie(
        settings.cookie_name,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=settings.production,
        samesite="strict",
        path="/",
    )
    return {"ok": True}


@router.get("/session", dependencies=[Depends(require_user)])
def session(request: Request):
    settings = request.app.state.settings
    return {
        "csrf": csrf_token(request),
        "local": settings.disable_auth,
        "expires": getattr(request.state, "session_expires", None),
    }


@router.post("/logout", dependencies=[Depends(require_user)])
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    db.execute(delete(AuthSession).where(AuthSession.digest == session_digest(request)))
    db.commit()
    settings = request.app.state.settings
    response.delete_cookie(
        settings.cookie_name, httponly=True, secure=settings.production, samesite="strict"
    )
    return {"ok": True}


@router.post("/logout-all", dependencies=[Depends(require_user)])
def logout_all(request: Request, response: Response, db: Session = Depends(get_db)):
    if db.execute(update(LoginLock).where(LoginLock.id == 1).values(id=1)).rowcount != 1:
        raise HTTPException(503, "Блокировка входа недоступна")
    db.execute(delete(AuthSession))
    db.commit()
    settings = request.app.state.settings
    response.delete_cookie(
        settings.cookie_name, httponly=True, secure=settings.production, samesite="strict"
    )
    return {"ok": True}
