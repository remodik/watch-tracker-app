import os
import time
import json
import secrets

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, String, Integer, Text, BigInteger
from sqlalchemy.orm import sessionmaker, declarative_base, Session

# ---------- DB setup ----------
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./watchlist.db")
# Railway/Neon sometimes give "postgres://" — SQLAlchemy 2.x wants "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Item(Base):
    __tablename__ = "items"
    id = Column(String, primary_key=True)
    added = Column(BigInteger, nullable=False)
    type = Column(String, nullable=False)  # 'anime' | 'film'
    title = Column(Text, nullable=False)
    year = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="watched")
    genres = Column(Text, nullable=False, default="[]")  # JSON-encoded list
    seasonsDone = Column(Integer, nullable=False, default=0)
    seasonsTotal = Column(Integer, nullable=False, default=0)
    note = Column(Text, nullable=False, default="")


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def row_to_dict(i: Item) -> dict:
    return {
        "id": i.id,
        "added": i.added,
        "type": i.type,
        "title": i.title,
        "year": i.year,
        "status": i.status,
        "genres": json.loads(i.genres or "[]"),
        "seasonsDone": i.seasonsDone,
        "seasonsTotal": i.seasonsTotal,
        "note": i.note or "",
    }


# ---------- auth ----------
APP_TOKEN = os.environ.get("APP_TOKEN")  # set this in Railway env vars


def check_auth(x_auth_token: Optional[str] = Header(None)):
    if APP_TOKEN and x_auth_token != APP_TOKEN:
        raise HTTPException(status_code=401, detail="Неверный токен")
    return True


# ---------- schemas ----------
class ItemIn(BaseModel):
    type: str
    title: str
    year: int | None= None
    status: str = "watched"
    genres: list[str] = Field(default_factory=list)
    seasonsDone: int = 0
    seasonsTotal: int = 0
    note: str = ""


class ItemOut(ItemIn):
    id: str
    added: int


class BulkImport(BaseModel):
    mode: str  # 'merge' | 'replace'
    items: list[dict]


# ---------- app ----------
app = FastAPI(title="Архив просмотренного API")


def norm(s: str) -> str:
    return " ".join(str(s or "").strip().lower().split())


@app.get("/api/items", response_model=list[ItemOut])
def list_items(db: Session = Depends(get_db), _=Depends(check_auth)):
    rows = db.query(Item).order_by(Item.added.desc()).all()
    return [row_to_dict(r) for r in rows]


@app.post("/api/items", response_model=ItemOut)
def create_item(payload: ItemIn, db: Session = Depends(get_db), _=Depends(check_auth)):
    dup = db.query(Item).filter(Item.title.isnot(None)).all()
    for d in dup:
        if norm(d.title) == norm(payload.title):
            raise HTTPException(status_code=409, detail=f"«{d.title}» уже есть в коллекции")
    new_id = secrets.token_hex(4)
    item = Item(
        id=new_id,
        added=int(time.time() * 1000),
        type=payload.type,
        title=payload.title,
        year=payload.year,
        status=payload.status,
        genres=json.dumps(payload.genres, ensure_ascii=False),
        seasonsDone=payload.seasonsDone,
        seasonsTotal=payload.seasonsTotal,
        note=payload.note,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return row_to_dict(item)


@app.put("/api/items/{item_id}", response_model=ItemOut)
def update_item(item_id: str, payload: ItemIn, db: Session = Depends(get_db), _=Depends(check_auth)):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    others = db.query(Item).filter(Item.id != item_id).all()
    for d in others:
        if norm(d.title) == norm(payload.title):
            raise HTTPException(status_code=409, detail=f"«{d.title}» уже есть в коллекции")
    item.type = payload.type
    item.title = payload.title
    item.year = payload.year
    item.status = payload.status
    item.genres = json.dumps(payload.genres, ensure_ascii=False)
    item.seasonsDone = payload.seasonsDone
    item.seasonsTotal = payload.seasonsTotal
    item.note = payload.note
    db.commit()
    db.refresh(item)
    return row_to_dict(item)


@app.delete("/api/items/{item_id}")
def delete_item(item_id: str, db: Session = Depends(get_db), _=Depends(check_auth)):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Запись не найдена")
    db.delete(item)
    db.commit()
    return {"ok": True}


@app.post("/api/items/bulk-import")
def bulk_import(payload: BulkImport, db: Session = Depends(get_db), _=Depends(check_auth)):
    added = 0
    if payload.mode == "replace":
        db.query(Item).delete()
        db.commit()
    existing_titles = {norm(r.title) for r in db.query(Item).all()}
    for d in payload.items:
        title = (d.get("title") or "").strip()
        if not title:
            continue
        if norm(title) in existing_titles:
            continue
        new_id = secrets.token_hex(4)
        item = Item(
            id=new_id,
            added=int(d.get("added") or time.time() * 1000),
            type=d.get("type", "anime"),
            title=title,
            year=d.get("year"),
            status=d.get("status", "watched"),
            genres=json.dumps(d.get("genres") or [], ensure_ascii=False),
            seasonsDone=int(d.get("seasonsDone") or 0),
            seasonsTotal=int(d.get("seasonsTotal") or 0),
            note=d.get("note") or "",
        )
        db.add(item)
        existing_titles.add(norm(title))
        added += 1
    db.commit()
    return {"added": added}


@app.get("/api/health")
def health():
    return {"ok": True}


# ---------- static frontend ----------
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
