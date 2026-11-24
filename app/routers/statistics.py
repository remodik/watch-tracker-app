from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_db, require_user
from app.models import Item
from app.services.library import item_response
from app.services.statistics import distributions, report, summary_items, upcoming

router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])
DB = Annotated[Session, Depends(get_db)]


@router.get("/dashboard")
def dashboard(db: DB):
    def rows(*where, order=Item.added, limit=6):
        result = db.scalars(select(Item).where(*where).order_by(order.desc(), Item.id).limit(limit))
        return [item_response(item) for item in result]

    completed = Item.tracking["completed"].as_string()
    return {
        "stats": distributions(summary_items(db)),
        "continuing": rows(Item.status.in_(["watching", "rewatching"]), order=Item.updated),
        "recent": rows(),
        "completed": rows(Item.status == "watched", completed.is_not(None), order=completed),
        "favorites": rows(Item.favorite.is_(True)),
        "releases": upcoming(db, limit=4),
    }


@router.get("/statistics")
def statistics(
    db: DB,
    year: Annotated[int | None, Query(ge=1870, le=2200)] = None,
    tz: Annotated[str, Query(max_length=100)] = "UTC",
):
    try:
        zone = ZoneInfo(tz)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise HTTPException(422, "Неизвестный часовой пояс") from exc
    return report(db, year or datetime.now(zone).year, zone)


@router.get("/calendar")
def calendar(db: DB):
    return upcoming(db)
