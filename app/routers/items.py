from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import lock_library
from app.dependencies import get_db, require_user
from app.models import WatchEvent
from app.schemas import (
    FavoriteChange,
    Identifier,
    ItemFilters,
    ItemInput,
    Progress,
    StatusChange,
)
from app.services.import_export import create_backup, prune_automatic_backups
from app.services.library import (
    add_item,
    archive_event,
    archive_item,
    change_progress,
    duplicate,
    get_item,
    item_response,
    list_items,
    set_status,
    touch_item,
    update_item,
)

router = APIRouter(prefix="/api/items", dependencies=[Depends(require_user)])
DB = Annotated[Session, Depends(get_db)]


@router.get("")
def listing(filters: Annotated[ItemFilters, Query()], db: DB):
    return list_items(db, filters)


@router.post("", status_code=201)
def create(payload: ItemInput, db: DB):
    lock_library(db)
    match = duplicate(db, payload)
    if match:
        raise HTTPException(409, {"message": "Произведение уже в коллекции", "id": match.id})
    item = add_item(db, payload)
    db.commit()
    return item_response(item)


@router.get("/detail")
def detail(id: Identifier, db: DB):
    item = get_item(db, id)
    events = db.scalars(
        select(WatchEvent)
        .where(WatchEvent.item_id == id)
        .order_by(WatchEvent.at.desc(), WatchEvent.id.desc())
        .limit(100)
    )
    return {"item": item_response(item), "events": [archive_event(event) for event in events]}


@router.put("/detail")
def update(
    id: Identifier,
    payload: ItemInput,
    db: DB,
    expected: Identifier | None = None,
    confirm_type_change: bool = False,
):
    lock_library(db)
    item = get_item(db, id)
    if expected is not None and expected != item.revision:
        raise HTTPException(
            409, "Запись изменилась в другой вкладке. Откройте редактирование заново."
        )
    same_identity = (
        item.title,
        item.type,
        item.year,
        item.metadata_json.get("provider"),
        item.metadata_json.get("externalId"),
    ) == (
        payload.title,
        payload.type,
        payload.year,
        payload.metadata.provider,
        payload.metadata.externalId,
    )
    match = duplicate(db, payload, excluding=id) if not same_identity else None
    if match:
        raise HTTPException(409, {"message": "Произведение уже в коллекции", "id": match.id})
    if item.type != payload.type and confirm_type_change:
        copy = create_backup(db, "type-change")
        prune_automatic_backups(db, copy)
    update_item(db, item, payload, confirm_type_change)
    db.commit()
    return item_response(item)


@router.delete("/detail")
def remove(id: Identifier, db: DB):
    lock_library(db)
    item = get_item(db, id)
    backup = create_backup(db, "delete")
    db.delete(item)
    prune_automatic_backups(db, backup)
    db.commit()
    return {"ok": True, "backupId": backup.id}


@router.post("/progress")
def progress(id: Identifier, payload: Progress, db: DB):
    lock_library(db)
    item = get_item(db, id)
    change_progress(db, item, payload)
    db.commit()
    return item_response(item)


@router.post("/status")
def status(id: Identifier, payload: StatusChange, db: DB):
    lock_library(db)
    item = get_item(db, id)
    set_status(db, item, payload.status)
    db.commit()
    return item_response(item)


@router.post("/favorite")
def favorite(id: Identifier, payload: FavoriteChange, db: DB):
    lock_library(db)
    item = get_item(db, id)
    item.favorite = payload.favorite
    touch_item(item)
    db.commit()
    return item_response(item)


@router.put("/{id:path}", include_in_schema=False)
def legacy_update(id: Identifier, payload: ItemInput, db: DB):
    # The old API sent only the original fields. Preserve newer fields on those requests.
    lock_library(db)
    current = get_item(db, id)
    fields = archive_item(current)
    for key in ("id", "added", "updated", "legacyDuplicate"):
        fields.pop(key, None)
    fields.update(payload.model_dump(exclude_unset=True))
    from pydantic import ValidationError

    try:
        data = ItemInput.model_validate(fields)
    except ValidationError as exc:
        raise HTTPException(422, "Проверьте сочетание полей") from exc
    match = (
        duplicate(db, data, excluding=id)
        if (current.title, current.type, current.year)
        != (
            data.title,
            data.type,
            data.year,
        )
        or "metadata" in payload.model_fields_set
        else None
    )
    if match:
        raise HTTPException(409, "Произведение уже в коллекции")
    update_item(db, current, data)
    db.commit()
    return item_response(current)


@router.delete("/{id:path}", include_in_schema=False)
def legacy_remove(id: Identifier, db: DB):
    return remove(id, db)
