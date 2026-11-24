from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import begin_library_snapshot, lock_library
from app.dependencies import get_db, require_user
from app.identity import fingerprint
from app.models import Backup, LibraryLock
from app.schemas import ArchiveRequest, BackupRestore, Identifier, ImportRequest
from app.services.import_export import apply_import, create_backup, export_library, plan_import

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])
DB = Annotated[Session, Depends(get_db)]


def download(data, filename):
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export")
def export(db: DB):
    begin_library_snapshot(db)
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
            select(Backup.id, Backup.created, Backup.reason, Backup.size_bytes)
            .order_by(Backup.created.desc(), Backup.id)
            .limit(51)
            .offset((page - 1) * 50)
        )
        .mappings()
        .all()
    )
    return {
        "items": [dict(row) for row in rows[:50]],
        "more": len(rows) > 50,
        "total_bytes": db.scalar(select(func.coalesce(func.sum(Backup.size_bytes), 0))),
    }


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


def stored_archive(db, id):
    backup = db.get(Backup, id)
    if backup is None:
        raise HTTPException(404, "Резервная копия отсутствует")
    try:
        archive = backup.archive
        return ArchiveRequest.model_validate(
            {
                "mode": "replace",
                "confirm": True,
                "version": archive["version"],
                "items": archive["items"],
                "events": archive.get("events", []),
            }
        )
    except (KeyError, TypeError, ValidationError) as error:
        raise HTTPException(422, "Резервная копия повреждена") from error


@router.get("/backups/{id}/restore-preview")
def restore_preview(id: Identifier, db: DB):
    begin_library_snapshot(db)
    generation = db.scalar(select(LibraryLock.generation).where(LibraryLock.id == 1))
    if generation is None:
        raise HTTPException(503, "Блокировка коллекции недоступна")
    payload = stored_archive(db, id)
    return {**plan_import(db, payload).summary(), "preview": fingerprint(id, generation)}


@router.post("/backups/{id}/restore")
def restore(id: Identifier, confirmation: BackupRestore, db: DB):
    generation = lock_library(db)
    if confirmation.preview != fingerprint(id, generation):
        raise HTTPException(409, "Коллекция изменилась. Повторите предпросмотр.")
    payload = stored_archive(db, id)
    return apply_import(db, payload, plan_import(db, payload), backup_reason="restore")


@router.delete("/backups/{id}")
def delete_backup(id: Identifier, db: DB):
    lock_library(db)
    backup = db.get(Backup, id)
    if backup is None:
        raise HTTPException(404, "Резервная копия отсутствует")
    db.delete(backup)
    db.commit()
    return {"ok": True}
