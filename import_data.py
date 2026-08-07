"""
Разовый импорт watchlist.json в базу данных.

Запуск локально (SQLite):
    python import_data.py watchlist.json

Запуск против удалённой базы (Neon/Postgres) — задай DATABASE_URL перед запуском:
    DATABASE_URL="postgresql://user:pass@host/dbname?sslmode=require" python import_data.py watchlist.json

Скрипт пишет напрямую в базу через SQLAlchemy (без HTTP/токена), дубликаты по
названию (без учёта регистра) пропускаются.
"""
import sys
import json

from main import SessionLocal, Item, norm

def main():
    if len(sys.argv) < 2:
        print("Использование: python import_data.py watchlist.json")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print("Файл должен содержать JSON-массив записей")
        sys.exit(1)

    db = SessionLocal()
    existing = {norm(r.title) for r in db.query(Item).all()}
    added = 0
    for d in data:
        title = (d.get("title") or "").strip()
        if not title or norm(title) in existing:
            continue
        item = Item(
            id=d.get("id") or __import__("secrets").token_hex(4),
            added=int(d.get("added") or 0) or __import__("time").time_ns() // 1_000_000,
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
        existing.add(norm(title))
        added += 1
    db.commit()
    db.close()
    print(f"Импортировано записей: {added} (из {len(data)} в файле)")


if __name__ == "__main__":
    main()
