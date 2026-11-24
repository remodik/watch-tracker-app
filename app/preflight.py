"""Inspect a legacy watchlist database without modifying it."""

import argparse
import json
from collections import Counter

from pydantic import ValidationError
from sqlalchemy import MetaData, Table, inspect, select
from sqlalchemy.exc import SQLAlchemyError

from app.config import database_url
from app.database import make_engine
from app.identity import match_key
from app.schemas import ArchiveItem
from app.services.import_export import validation_messages


def inspect_items(connection):
    if not inspect(connection).has_table("items"):
        return {"count": 0, "invalid": [], "duplicates": 0}
    table = Table("items", MetaData(), autoload_with=connection)
    seen = Counter()
    invalid = []
    count = 0
    for row in connection.execute(select(table).order_by(table.c.id)).mappings():
        count += 1
        fields = {
            key: row[key]
            for key in (
                "id",
                "added",
                "type",
                "title",
                "year",
                "status",
                "seasonsDone",
                "seasonsTotal",
                "note",
            )
        }
        issues = []
        try:
            fields["genres"] = json.loads(row["genres"])
        except (TypeError, ValueError):
            issues.append({"field": "genres", "message": "Некорректный JSON"})
        if "updated" in row:
            fields.update({key: row[key] for key in ("updated", "favorite", "rating")})
            if isinstance(row["tracking"], dict):
                fields.update(row["tracking"])
            fields["metadata"] = row["metadata_json"]
        try:
            ArchiveItem.model_validate(fields)
        except ValidationError as exc:
            # Validation text may contain user values from custom validators.
            issues.extend(
                {"field": issue["field"], "message": "Нарушение схемы"}
                for issue in validation_messages(exc)
            )
        if issues:
            invalid.append({"row": count, "issues": issues})
        if isinstance(row["title"], str):
            seen[match_key(row["title"], row["type"], row["year"])] += 1
    return {"count": count, "invalid": invalid, "duplicates": sum(n - 1 for n in seen.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Read-only inspection (default)")
    parser.parse_args()
    from dotenv import load_dotenv

    load_dotenv()
    engine = make_engine(database_url(direct=True))
    try:
        with engine.connect() as connection, connection.begin():
            if engine.dialect.name == "postgresql":
                connection.exec_driver_sql(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
            else:
                connection.exec_driver_sql("PRAGMA query_only=ON")
                connection.exec_driver_sql("BEGIN")
            report = inspect_items(connection)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2 if report["invalid"] else 0
    except SQLAlchemyError:
        parser.exit(1, "Не удалось проверить схему базы.\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
