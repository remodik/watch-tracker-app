import json
from collections import defaultdict
from dataclasses import dataclass, field

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.models import Backup, Item, WatchEvent
from app.schemas import ArchiveEvent, ArchiveItem
from app.services.library import (
    add_item,
    archive_event,
    archive_item,
    assign,
    identity,
    match_duplicate,
    now_ms,
    uuid,
)


def export_library(db):
    return {
        "version": 2,
        "exported": now_ms(),
        "items": [
            archive_item(item) for item in db.scalars(select(Item).order_by(Item.added, Item.id))
        ],
        "events": [
            archive_event(event)
            for event in db.scalars(select(WatchEvent).order_by(WatchEvent.at, WatchEvent.id))
        ],
    }


def create_backup(db, reason):
    archive = export_library(db)
    size = len(json.dumps(archive, ensure_ascii=False, separators=(",", ":")).encode())
    backup = Backup(id=uuid(), created=now_ms(), reason=reason, archive=archive, size_bytes=size)
    db.add(backup)
    return backup


def prune_automatic_backups(db):
    settings = db.info.get("settings")
    days = settings.backup_retention_days if settings else 30
    limit = settings.backup_max_automatic_count if settings else 20
    cutoff = now_ms() - days * 86_400_000
    db.flush()
    ordered = (
        select(Backup.id, Backup.created)
        .where(Backup.reason != "manual")
        .order_by(Backup.created.desc(), Backup.id.desc())
    )
    obsolete = [
        backup_id
        for index, (backup_id, created) in enumerate(db.execute(ordered))
        if index and (index >= limit or created < cutoff)
    ]
    for start in range(0, len(obsolete), 500):
        db.execute(delete(Backup).where(Backup.id.in_(obsolete[start : start + 500])))


def validation_messages(exc):
    return [
        {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
        for error in exc.errors(include_input=False, include_context=False, include_url=False)
    ]


def legacy_entry(raw):
    if not isinstance(raw, dict):
        return raw
    data = dict(raw)
    for name, default in (("genres", []), ("note", ""), ("seasonsDone", 0), ("seasonsTotal", 0)):
        if name in data and data[name] is None:
            data[name] = default
    for name in ("year", "added", "seasonsDone", "seasonsTotal"):
        value = data.get(name)
        if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 15:
            data[name] = int(value)
    return data


@dataclass
class Plan:
    entries: list = field(default_factory=list)
    events: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    duplicates: int = 0
    added: int = 0
    updated: int = 0

    def summary(self):
        return {
            "added": self.added,
            "updated": self.updated,
            "duplicates": self.duplicates,
            "invalid": len(self.errors),
            "errors": self.errors[:200],
            "events": len(self.events),
        }


def indexed_import_candidates(db, entries):
    matches, externals, ids = set(), set(), set()
    for _, item in entries:
        match, external = identity(item)
        matches.add(match)
        if external:
            externals.add(external)
        if item.id:
            ids.add(item.id)

    rows = {}
    for column, keys in ((Item.match_key, matches), (Item.identity_key, externals), (Item.id, ids)):
        keys = list(keys)
        for start in range(0, len(keys), 500):
            for item in db.scalars(select(Item).where(column.in_(keys[start : start + 500]))):
                rows[item.id] = item

    by_match = defaultdict(list)
    by_external = {}
    for item in sorted(rows.values(), key=lambda entry: (entry.added, entry.id)):
        by_match[item.match_key].append(item)
        if item.identity_key:
            by_external[item.identity_key] = item
    return by_match, by_external, rows


def plan_import(db, payload):
    plan = Plan()
    source_ids, id_mapping, destination_ids = set(), {}, set()
    matches, externals = {}, {}
    replace = payload.mode == "replace"
    parsed_items = []
    for index, raw in enumerate(payload.items, 1):
        try:
            data = ArchiveItem.model_validate(legacy_entry(raw) if payload.version == 1 else raw)
        except ValidationError as exc:
            plan.errors.append(
                {"index": index, "record": "item", "issues": validation_messages(exc)}
            )
            continue
        parsed_items.append((index, data))
    by_match, by_external, by_id = (
        indexed_import_candidates(db, parsed_items) if not replace else ({}, {}, {})
    )
    for index, data in parsed_items:
        source = data.id
        if source and source in source_ids:
            plan.errors.append(
                {
                    "index": index,
                    "record": "item",
                    "issues": [{"message": "Идентификатор повторяется"}],
                }
            )
            continue
        if source:
            source_ids.add(source)
        match, external = identity(data)
        seen_external = matches.get(match, {})
        prior = externals.get(external) if external else None
        if prior is None and seen_external:
            prior = seen_external.get(None) if external else next(iter(seen_external.values()))
        legacy_duplicate = (
            replace and payload.version == 2 and data.legacyDuplicate and not external and source
        )
        if prior and not legacy_duplicate:
            plan.duplicates += 1
            if source:
                id_mapping[source] = prior
            continue
        candidates = by_match.get(match, [])
        external_candidate = by_external.get(external)
        if external_candidate is not None and external_candidate.match_key != match:
            candidates = sorted(
                [*candidates, external_candidate], key=lambda entry: (entry.added, entry.id)
            )
        existing = match_duplicate(candidates, match, external)
        collision = by_id.get(source)
        if collision and (existing is None or collision.id != existing.id):
            old_external = collision.metadata_json.get("externalId")
            if existing or (
                old_external
                and data.metadata.externalId
                and (
                    old_external != data.metadata.externalId
                    or collision.metadata_json.get("provider") != data.metadata.provider
                )
            ):
                plan.errors.append(
                    {
                        "index": index,
                        "record": "item",
                        "issues": [{"message": "Конфликт идентификатора"}],
                    }
                )
                continue
            existing = collision
        target = existing.id if existing else (source or uuid())
        if target in destination_ids:
            plan.duplicates += 1
            if source:
                id_mapping[source] = target
            continue
        destination_ids.add(target)
        if not legacy_duplicate:
            matches.setdefault(match, {}).setdefault(external, target)
        if external:
            externals[external] = target
        if source:
            id_mapping[source] = target
        data.id = target
        if existing:
            plan.duplicates += 1
            if payload.mode == "update":
                if payload.version == 1:
                    current = archive_item(existing)
                    for key in ("legacyDuplicate",):
                        current.pop(key, None)
                    current.update(data.model_dump(exclude_unset=True))
                    try:
                        data = ArchiveItem.model_validate(current)
                    except ValidationError as exc:
                        plan.errors.append(
                            {"index": index, "record": "item", "issues": validation_messages(exc)}
                        )
                        continue
                plan.entries.append((data, existing))
                plan.updated += 1
        else:
            plan.entries.append((data, None))
            plan.added += 1

    seen_events = set()
    for index, raw in enumerate(payload.events, 1):
        try:
            event = ArchiveEvent.model_validate(raw)
        except ValidationError as exc:
            plan.errors.append(
                {"index": index, "record": "event", "issues": validation_messages(exc)}
            )
            continue
        target = id_mapping.get(event.item_id)
        if not target or event.id in seen_events:
            plan.errors.append(
                {
                    "index": index,
                    "record": "event",
                    "issues": [{"message": "Повтор события или запись отсутствует"}],
                }
            )
            continue
        seen_events.add(event.id)
        event.item_id = target
        old = db.get(WatchEvent, event.id) if not replace else None
        event_data = event.data.model_dump(exclude_defaults=True)
        if old:
            if (
                old.item_id != target
                or old.at != event.at
                or old.kind != event.kind
                or old.data != event_data
            ):
                plan.errors.append(
                    {
                        "index": index,
                        "record": "event",
                        "issues": [{"message": "Конфликт истории просмотра"}],
                    }
                )
        else:
            plan.events.append(
                WatchEvent(
                    id=event.id,
                    item_id=target,
                    at=event.at,
                    kind=event.kind,
                    data=event_data,
                )
            )
    return plan


def apply_import(db, payload, plan, backup_reason=None):
    if plan.errors:
        raise HTTPException(422, detail=plan.summary())
    replace = payload.mode == "replace"
    if replace and not payload.confirm:
        raise HTTPException(409, "Подтвердите замену всей коллекции")
    backup = create_backup(db, backup_reason or payload.mode) if replace or plan.updated else None
    if replace:
        db.execute(delete(WatchEvent))
        db.execute(delete(Item))
    for data, item in plan.entries:
        if item is None:
            created = add_item(db, data, imported=True)
            if (
                replace
                and payload.version == 2
                and data.legacyDuplicate
                and not data.metadata.externalId
            ):
                created.identity_key = None
        else:
            previous = item.identity_key
            assign(item, data, data.updated if data.updated is not None else now_ms())
            if previous is None and not data.metadata.externalId:
                item.identity_key = None
    db.flush()
    db.add_all(plan.events)
    if backup:
        prune_automatic_backups(db)
    db.commit()
    return {**plan.summary(), "backupId": backup.id if backup else None}
