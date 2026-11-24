from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import lock_library
from app.dependencies import get_db, require_user
from app.models import Backup
from app.schemas import Identifier, ImportRequest
from app.services.import_export import apply_import, create_backup, export_library, plan_import

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])
DB = Annotated[Session, Depends(get_db)]


def download(data, filename):
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export")
def export(db: DB):
    lock_library(db)
    return download(export_library(db), "watchlist.json")


@router.post("/items/bulk-import/preview")
def preview(payload: ImportRequest, db: DB):
    return plan_import(db, payload).summary()


@router.post("/items/bulk-import")
def import_items(payload: ImportRequest, db: DB):
    lock_library(db)
    return apply_import(db, payload, plan_import(db, payload))


@router.get("/backups")
def backups(db: DB, page: Annotated[int, Query(ge=1, le=10_000)] = 1):
    rows = (
        db.execute(
            select(Backup.id, Backup.created, Backup.reason)
            .order_by(Backup.created.desc(), Backup.id)
            .limit(51)
            .offset((page - 1) * 50)
        )
        .mappings()
        .all()
    )
    return {"items": [dict(row) for row in rows[:50]], "more": len(rows) > 50}


@router.post("/backups", status_code=201)
def snapshot(db: DB):
    lock_library(db)
    backup = create_backup(db, "manual")
    db.commit()
    return {"id": backup.id, "created": backup.created, "reason": backup.reason}


@router.get("/backups/{id}")
def get_backup(id: Identifier, db: DB):
    backup = db.get(Backup, id)
    if backup is None:
        raise HTTPException(404, "Резервная копия отсутствует")
    return download(backup.archive, f"watchlist-{backup.id}.json")
